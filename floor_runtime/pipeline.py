"""Execute an admitted pipeline. Total, deterministic, pure.

This module is the ONE executor. The admission gate proves a pipeline by
running it here, and the shipped runtime answers by running it here — so what
was proved is exactly what runs. There is no eval, no exec and no imports
beyond the standard library; an op outside the vocabulary is refused rather
than interpreted.

Grammar (validated before anything runs):

    rows  (filter | join)*  [group_by]  reducer  [top]

Column names: the base table's columns are bare (``amount``); a joined table's
columns are qualified (``vendors.region``).

Exact arithmetic. Numbers are parsed to Decimal, never binary floats: sums,
max and min are exact (2**53 + 1 stays 2**53 + 1). A sum that cannot be held
exactly is refused. The only rounding anywhere is the mean, which is rounded
half-even to MEAN_PLACES decimal places — and says so in its readback.

Fail closed on data, not only on specs. Each of these raises DataError instead
of returning a plausible number:

  * a value in a numeric position that is not a number ("N/A", "1.200,50");
  * a value in a date position that is not an ISO date ("03/04/2026");
  * a join key that is not unique on the joined side (it would multiply rows);
  * a row with no match in a join, unless the spec explicitly says what to do
    with it ("how": "left" keeps it, "how": "inner" drops it) — the default
    refuses, because a silently dropped row makes every total quietly low;
  * a table entry that is not a row at all (corrupt JSON element).
"""
from __future__ import annotations

import datetime as _dt
import decimal
import math
import re
from decimal import Decimal

START = "rows"
MID_OPS = {"filter", "join"}
GROUP_OP = "group_by"
REDUCERS = {"count", "sum", "mean", "max", "min", "distinct", "count_missing",
            "earliest", "latest"}
POST_OPS = {"top"}
ROW_OPS = {START} | MID_OPS
ALL_OPS = ROW_OPS | {GROUP_OP} | REDUCERS | POST_OPS

FILTER_FORMS = {"equals", "not_equals", "in", "contains", "nonempty", "empty",
                "gt", "lt", "gte", "lte",
                "after", "before", "on_or_after", "on_or_before"}
NUM_BOUNDS = {"gt", "lt", "gte", "lte"}
DATE_BOUNDS = {"after", "before", "on_or_after", "on_or_before"}
JOIN_MODES = {"strict", "left", "inner"}      # strict (default) refuses unmatched rows
BUCKETS = {"day", "week", "month", "year"}
MAX_GROUPS = 1000       # an ungrouped answer bigger than this needs a top step
MAX_TOP = 1000
MAX_DIGITS = 38         # significant digits a number may carry (SQL DECIMAL(38))
MAX_EXPONENT = 60       # |exponent| beyond this is not a business number
MEAN_PLACES = 10
MISSING_GROUP = "(missing)"

_FIELDS = {"rows": set(),
           "filter": {"column"} | FILTER_FORMS,
           "join": {"table", "on", "to", "how"},
           "group_by": {"column", "bucket"},
           "top": {"n", "order"}}
_FIELDS.update({r: {"column"} for r in REDUCERS})

# Exact: any rounding raises. Used for every sum.
_EXACT = decimal.Context(prec=100, rounding=decimal.ROUND_HALF_EVEN,
                         traps=[decimal.Inexact, decimal.InvalidOperation,
                                decimal.Overflow, decimal.DivisionByZero])
# Rounding allowed (the mean only), then quantized to MEAN_PLACES.
_ROUNDING = decimal.Context(prec=100, rounding=decimal.ROUND_HALF_EVEN,
                            traps=[decimal.InvalidOperation, decimal.Overflow,
                                   decimal.DivisionByZero])
_MEAN_QUANTUM = Decimal(1).scaleb(-MEAN_PLACES)


class PipelineError(ValueError):
    """The pipeline is not executable. Raised on load, never mid-answer."""


class DataError(ValueError):
    """The data cannot support a trustworthy answer. Refuse; never guess.

    `public` is the same reason with the offending VALUES removed — safe to
    write to a log that may be sent back to Perslis."""

    def __init__(self, message: str, public: str | None = None):
        super().__init__(message)
        self.public = public or message


# ─────────────────────────── value parsing ───────────────────────────────

_MONEY = re.compile(r"^([-+]?)\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?$")
_PLAIN = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")
_ISO_DATE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?)?$")


def missing(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _missing_typed(v) -> bool:
    """Missing in a numeric/date position. SQL dumps write NULL for nothing."""
    return missing(v) or (isinstance(v, str) and v.strip() in ("NULL", "null"))


def parse_number(v):
    """Decimal, or None when v is not unambiguously a number.

    Accepts plain numbers, scientific notation and US currency formatting
    ("$1,200.50", "-$5"). Refuses anything a reader could take two ways
    ("1.200,50"), non-finite values, and numbers beyond MAX_DIGITS significant
    digits or MAX_EXPONENT. Floats (SQLite REAL) are taken at their shortest
    repr, i.e. the digits a person would read, not their binary expansion.
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, Decimal):
        d = v
    elif isinstance(v, int):
        d = Decimal(v)
    elif isinstance(v, float):
        if not math.isfinite(v):
            return None
        d = Decimal(repr(v))
    elif isinstance(v, str):
        s = v.strip()
        m = _MONEY.match(s)
        if m:
            s = m.group(1) + m.group(2).replace(",", "") + (m.group(3) or "")
        elif not _PLAIN.match(s):
            return None
        try:
            d = Decimal(s)
        except decimal.InvalidOperation:
            return None
    else:
        return None
    if (not d.is_finite() or len(d.as_tuple().digits) > MAX_DIGITS
            or abs(d.adjusted()) > MAX_EXPONENT):
        return None
    return d


def parse_date(v):
    """datetime.date at day granularity, or None. ISO 8601 only; time and
    timezone are ignored (documented: date operations compare calendar days)."""
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    if not isinstance(v, str):
        return None
    m = _ISO_DATE.match(v.strip())
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def text(v) -> str:
    """Canonical text for equality, grouping and join keys."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Decimal) and v.is_finite():
        return str(int(v)) if v == v.to_integral_value() else format(v.normalize(), "f")
    if isinstance(v, float) and math.isfinite(v) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def to_plain(v):
    """JSON-safe values with no loss: Decimal -> int when integral, -> float when
    the float's shortest repr is the same number, else an exact decimal string."""
    if isinstance(v, dict):
        return {k: to_plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [to_plain(x) for x in v]
    if isinstance(v, Decimal):
        if v == v.to_integral_value():
            return int(v)
        f = float(v)
        return f if math.isfinite(f) and Decimal(repr(f)) == v else format(v.normalize(), "f")
    return v


def _bad(kind: str, col: str, bad: list) -> DataError:
    public = f"{len(bad)} value(s) in '{col}' are not {kind}"
    shown = ", ".join(repr(b) for b in bad[:3])
    return DataError(f"{public}: {shown}", public)


def _looks_numeric(v) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) or (
        isinstance(v, str) and bool(_MONEY.match(v.strip()) or _PLAIN.match(v.strip())))


def _numbers(rows: list, col: str) -> list:
    """[(row, Decimal)] for rows with a value; DataError if any value is not a number."""
    out, bad = [], []
    for r in rows:
        v = r.get(col)
        if _missing_typed(v):
            continue
        n = parse_number(v)
        if n is None:
            bad.append(v)
        else:
            out.append((r, n))
    if bad:
        if all(_looks_numeric(b) for b in bad):
            raise _bad(f"within the exact-number limit ({MAX_DIGITS} significant digits, "
                       f"exponent ±{MAX_EXPONENT})", col, bad)
        raise _bad("numbers", col, bad)
    return out


def _within_policy(d: Decimal, col: str, what: str) -> Decimal:
    """Results obey the same exact-number policy as inputs."""
    if len(d.as_tuple().digits) > MAX_DIGITS or abs(d.adjusted()) > MAX_EXPONENT:
        raise DataError(f"the {what} of '{col}' is beyond the exact-number limit "
                        f"({MAX_DIGITS} significant digits, exponent ±{MAX_EXPONENT})")
    return d


def _dates(rows: list, col: str) -> list:
    """[(row, date)] for rows with a value; DataError if any value is not an ISO date."""
    out, bad = [], []
    for r in rows:
        v = r.get(col)
        if _missing_typed(v):
            continue
        d = parse_date(v)
        if d is None:
            bad.append(v)
        else:
            out.append((r, d))
    if bad:
        raise _bad("ISO dates (YYYY-MM-DD)", col, bad)
    return out


def exact_sum(vals: list, col: str = "value") -> Decimal:
    total = Decimal(0)
    try:
        for n in vals:
            total = _EXACT.add(total, n)
    except decimal.DecimalException:
        raise DataError(f"'{col}' cannot be added up exactly (magnitudes too far apart)") \
            from None
    return total


# ───────────────────────────── validation ────────────────────────────────

def _need_str(step: dict, key: str):
    if not isinstance(step.get(key), str) or not step[key].strip():
        raise PipelineError(f"'{step['op']}' needs a non-empty string '{key}'")


def _validate_step(step: dict) -> None:
    op = step["op"]
    extra = set(step) - {"op"} - _FIELDS[op]
    if extra:
        raise PipelineError(f"unknown field(s) {sorted(extra)} in '{op}' step")
    if op == "filter":
        _need_str(step, "column")
        forms = [k for k in FILTER_FORMS if k in step]
        if len(forms) != 1:
            raise PipelineError(
                f"filter needs exactly one of {sorted(FILTER_FORMS)}, got {forms}")
        form = forms[0]
        if form in ("nonempty", "empty") and step[form] is not True:
            raise PipelineError(f"filter '{form}' must be true")
        if form in NUM_BOUNDS and parse_number(step[form]) is None:
            raise PipelineError(f"filter '{form}' needs a number")
        if form in DATE_BOUNDS and parse_date(step[form]) is None:
            raise PipelineError(f"filter '{form}' needs an ISO date (YYYY-MM-DD)")
        if form == "in":
            vals = step["in"]
            if (not isinstance(vals, list) or not vals or len(vals) > 1000
                    or any(isinstance(x, (dict, list)) for x in vals)):
                raise PipelineError("filter 'in' needs a list of 1-1000 plain values")
        if form == "contains":
            _need_str(step, "contains")
    elif op == "join":
        for key in ("table", "on", "to"):
            _need_str(step, key)
        if step.get("how", "strict") not in JOIN_MODES:
            raise PipelineError(f"join 'how' must be one of {sorted(JOIN_MODES)}")
    elif op == "group_by":
        _need_str(step, "column")
        if "bucket" in step and step["bucket"] not in BUCKETS:
            raise PipelineError(f"group_by 'bucket' must be one of {sorted(BUCKETS)}")
    elif op in REDUCERS:
        if op == "count":
            if "column" in step:
                raise PipelineError("'count' takes no column (filter nonempty first)")
        else:
            _need_str(step, "column")
    elif op == "top":
        n = step.get("n")
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_TOP:
            raise PipelineError(f"top 'n' must be an integer 1-{MAX_TOP}")
        if step.get("order", "desc") not in ("desc", "asc"):
            raise PipelineError("top 'order' must be 'desc' or 'asc'")


def reducer_index(pipeline: list) -> int:
    for i, s in enumerate(pipeline):
        if s.get("op") in REDUCERS:
            return i
    return -1


def validate(pipeline) -> None:
    if not isinstance(pipeline, list) or not pipeline:
        raise PipelineError("pipeline must be a non-empty list")
    for step in pipeline:
        if not isinstance(step, dict) or "op" not in step:
            raise PipelineError(f"each step needs an 'op': {step!r}")
        if step["op"] not in ALL_OPS:
            raise PipelineError(f"unknown op '{step['op']}' — allowed: {sorted(ALL_OPS)}")
    if pipeline[0]["op"] != START:
        raise PipelineError("pipeline must start with {'op': 'rows'}")
    ri = reducer_index(pipeline)
    if ri < 0:
        raise PipelineError(
            f"pipeline must end in a reducer {sorted(REDUCERS)} (optionally then top)")
    tail = pipeline[ri + 1:]
    if [s["op"] for s in tail] not in ([], ["top"]):
        raise PipelineError("pipeline must end in a reducer; only one 'top' may follow it")
    middle = pipeline[1:ri]
    for i, step in enumerate(middle):
        op = step["op"]
        if op == GROUP_OP and i != len(middle) - 1:
            raise PipelineError("'group_by' must come directly before the reducer")
        if op not in MID_OPS and op != GROUP_OP:
            raise PipelineError(f"'{op}' cannot appear mid-pipeline")
    grouped = bool(middle) and middle[-1]["op"] == GROUP_OP
    if tail and not grouped:
        raise PipelineError("'top' ranks groups — it needs a group_by")
    for step in pipeline:
        _validate_step(step)


def describe(pipeline) -> str:
    """Compact derivation, e.g. rows -> filter(status equals 'paid') -> sum(amount)."""
    parts = []
    for s in pipeline:
        op = s["op"]
        if op == "join":
            how = s.get("how", "strict")
            parts.append(f"join({s['table']} on {s['on']}={s['to']}"
                         + {"strict": "", "left": ", keep unmatched",
                            "inner": ", drop unmatched"}[how] + ")")
        elif op == "filter":
            form = next(k for k in FILTER_FORMS if k in s)
            arg = "" if form in ("nonempty", "empty") else f" {s[form]!r}"
            parts.append(f"filter({s['column']} {form}{arg})")
        elif op == "group_by":
            parts.append(f"group_by({s['column']}"
                         + (f" by {s['bucket']}" if s.get("bucket") else "") + ")")
        elif op == "top":
            parts.append(f"top({s['n']}, {s.get('order', 'desc')}, ties kept)")
        else:
            parts.append(op + (f"({s['column']})" if s.get("column") else ""))
    return " -> ".join(parts)


# ────────────────────────────── execution ────────────────────────────────

def _cmp(form: str, bound):
    return {"gt": lambda x: x > bound, "lt": lambda x: x < bound,
            "gte": lambda x: x >= bound, "lte": lambda x: x <= bound,
            "after": lambda x: x > bound, "before": lambda x: x < bound,
            "on_or_after": lambda x: x >= bound, "on_or_before": lambda x: x <= bound}[form]


def _filter(rows: list, step: dict) -> list:
    col = step["column"]
    form = next(k for k in FILTER_FORMS if k in step)
    arg = step[form]
    if form == "equals":
        return [r for r in rows if text(r.get(col)) == text(arg)]
    if form == "not_equals":
        return [r for r in rows if text(r.get(col)) != text(arg)]
    if form == "in":
        allowed = {text(x) for x in arg}
        return [r for r in rows if text(r.get(col)) in allowed]
    if form == "contains":
        needle = arg.strip().lower()
        return [r for r in rows if needle in text(r.get(col)).lower()]
    if form == "nonempty":
        return [r for r in rows if not missing(r.get(col))]
    if form == "empty":
        return [r for r in rows if missing(r.get(col))]
    if form in NUM_BOUNDS:
        keep = _cmp(form, parse_number(arg))
        return [r for r, n in _numbers(rows, col) if keep(n)]
    keep = _cmp(form, parse_date(arg))
    return [r for r, d in _dates(rows, col) if keep(d)]


def _rows_of(ctx: dict, table: str):
    """The table's rows, None if absent; DataError if any entry is not a row."""
    rows = ctx.get(table)
    if not isinstance(rows, list):
        return None
    bad = sum(1 for r in rows if not isinstance(r, dict))
    if bad:
        raise DataError(f"table '{table}' has {bad} entr{'y' if bad == 1 else 'ies'} "
                        f"that are not rows — the data is corrupt")
    return rows


def _join(rows: list, right: list, step: dict) -> list:
    table, on, to = step["table"], step["on"], step["to"]
    how = step.get("how", "strict")
    index: dict = {}
    for r in right:
        if missing(r.get(to)):
            continue
        k = text(r.get(to))
        if k in index:
            tail = "joining would multiply rows and inflate every total"
            raise DataError(
                f"join key {table}.{to} is not unique ({k!r} appears more than once) — {tail}",
                f"join key {table}.{to} is not unique — {tail}")
        index[k] = r
    out, unmatched = [], []
    for r in rows:
        m = None if missing(r.get(on)) else index.get(text(r.get(on)))
        if m is None:
            if how == "left":
                out.append(dict(r))
            elif how == "strict":
                unmatched.append(r.get(on))
            continue                      # "inner": the signed spec chose to drop it
        merged = dict(r)
        merged.update({f"{table}.{c}": v for c, v in m.items()})
        out.append(merged)
    if unmatched:
        public = (f"{len(unmatched)} row(s) have no matching {table}.{to} — this tool "
                  f"refuses rather than silently leaving them out")
        shown = ", ".join(repr(u) for u in unmatched[:3])
        raise DataError(f"{public} (keys: {shown})", public)
    return out


def _bucket(d: _dt.date, bucket: str) -> str:
    if bucket == "day":
        return d.isoformat()
    if bucket == "month":
        return f"{d.year:04d}-{d.month:02d}"
    if bucket == "year":
        return f"{d.year:04d}"
    y, w, _ = d.isocalendar()
    return f"{y:04d}-W{w:02d}"


def _group(rows: list, step: dict) -> list:
    col, bucket = step["column"], step.get("bucket")
    groups: dict = {}
    if bucket:
        dated = {id(r): d for r, d in _dates(rows, col)}
        for r in rows:
            d = dated.get(id(r))
            groups.setdefault(MISSING_GROUP if d is None else _bucket(d, bucket),
                              []).append(r)
    else:
        for r in rows:
            v = r.get(col)
            groups.setdefault(MISSING_GROUP if missing(v) else text(v), []).append(r)
    return sorted(groups.items())


def _reduce(rows: list, step: dict):
    op, col = step["op"], step.get("column")
    if op == "count":
        return len(rows)
    if op == "count_missing":
        return sum(1 for r in rows if missing(r.get(col)))
    if op == "distinct":
        return len({text(r.get(col)) for r in rows if not missing(r.get(col))})
    if op in ("earliest", "latest"):
        ds = [d for _, d in _dates(rows, col)]
        if not ds:
            return None
        return (min(ds) if op == "earliest" else max(ds)).isoformat()
    vals = [n for _, n in _numbers(rows, col)]
    if op == "sum":
        return _within_policy(exact_sum(vals, col), col, "sum")
    if not vals:
        return None
    if op == "mean":
        total = exact_sum(vals, col)
        mean = _ROUNDING.divide(total, Decimal(len(vals))).quantize(
            _MEAN_QUANTUM, context=_ROUNDING)
        return _within_policy(mean.normalize() if mean == 0 else mean, col, "mean")
    return max(vals) if op == "max" else min(vals)


def _top(values: dict, step: dict) -> list:
    """The first n groups by value, WITH TIES: every group equal to the n-th is
    kept, so "which vendor has the most?" never silently picks one of two.
    Groups with no value are not ranked."""
    present = sorted(((k, v) for k, v in values.items() if v is not None),
                     key=lambda kv: kv[0])
    present.sort(key=lambda kv: kv[1], reverse=step.get("order", "desc") == "desc")
    n = step["n"]
    if len(present) <= n:
        return [[k, v] for k, v in present]
    cutoff = present[n - 1][1]
    end = n
    while end < len(present) and present[end][1] == cutoff:
        end += 1
    if end > MAX_TOP:
        raise DataError(f"top {n} is ambiguous: {end - n + 1} groups tie at {cutoff!r}",
                        f"top {n} is ambiguous: {end - n + 1} groups tie at the cutoff")
    return [[k, v] for k, v in present[:end]]


def row_stage(ctx: dict, entity: str, pipeline: list):
    """(rows that reach the reducer, the group_by step or None, evidence_found).

    Every filter and join, in order. run() is exactly this plus the reducer,
    so anything that inspects the surviving rows sees what execution sees."""
    rows = _rows_of(ctx, entity.split(".", 1)[0])
    if rows is None:
        return None, None, False
    group = None
    for step in pipeline[1:reducer_index(pipeline)]:
        op = step["op"]
        if op == "filter":
            rows = _filter(rows, step)
        elif op == "join":
            right = _rows_of(ctx, step["table"])
            if right is None:
                return None, None, False
            rows = _join(rows, right, step)
        else:
            group = step
    return rows, group, True


def run(ctx: dict, entity: str, pipeline: list):
    """(value, evidence_found). Values are exact (Decimal for numbers; use
    to_plain for JSON). Absent tables report absence; untrustworthy data raises
    DataError. Assumes validate() already passed."""
    rows, group, found = row_stage(ctx, entity, pipeline)
    if not found:
        return None, False
    ri = reducer_index(pipeline)
    reducer = pipeline[ri]
    if group is None:
        return _reduce(rows, reducer), True
    value = {k: _reduce(g, reducer) for k, g in _group(rows, group)}
    if ri + 1 < len(pipeline):
        return _top(value, pipeline[ri + 1]), True
    if len(value) > MAX_GROUPS:
        raise DataError(f"{len(value)} groups — more than {MAX_GROUPS}; "
                        f"add a 'top' step to rank them")
    return value, True


def values_equal(a, b) -> bool:
    """Does proposed value a match derived value b EXACTLY? Scalars, groups,
    rankings. Numbers compare as exact decimals — no tolerance."""
    if isinstance(b, dict):
        if not isinstance(a, dict):
            return False
        a2 = {text(k): v for k, v in a.items()}
        return set(a2) == set(b) and all(values_equal(a2[k], v) for k, v in b.items())
    if isinstance(b, list):
        if not isinstance(a, list) or len(a) != len(b):
            return False
        for x, y in zip(a, b):
            if isinstance(y, list) and len(y) == 2:       # a ranked [group, value] pair
                if not (isinstance(x, list) and len(x) == 2 and text(x[0]) == text(y[0])
                        and values_equal(x[1], y[1])):
                    return False
            elif not values_equal(x, y):
                return False
        return True
    if b is None or a is None:
        return a is None and b is None
    na, nb = parse_number(a), parse_number(b)
    if nb is not None:
        return na is not None and na == nb
    return text(a) == text(b)
