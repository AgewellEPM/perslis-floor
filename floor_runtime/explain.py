"""Plain-English readback of a pipeline — what the tool computes, in words.

A person reads this before a tool is signed ("does this answer the question
exactly?"), and a founder's AI client reads it in the tool description. It is
generated from the pipeline itself, so it cannot drift from what executes.
"""
from __future__ import annotations

from .pipeline import FILTER_FORMS, MEAN_PLACES, REDUCERS

_BOUND_WORDS = {"gt": "is greater than", "gte": "is at least", "lt": "is less than",
                "lte": "is at most", "after": "is after", "before": "is before",
                "on_or_after": "is on or after", "on_or_before": "is on or before"}


def _filter(s: dict) -> str:
    col = s["column"]
    form = next(k for k in FILTER_FORMS if k in s)
    arg = s[form]
    if form == "equals":
        return f"{col} is {arg!r}"
    if form == "not_equals":
        return f"{col} is not {arg!r}"
    if form == "in":
        return f"{col} is one of " + ", ".join(repr(x) for x in arg)
    if form == "contains":
        return f"{col} contains {arg!r} (ignoring case)"
    if form == "nonempty":
        return f"{col} has a value"
    if form == "empty":
        return f"{col} is empty"
    return f"{col} {_BOUND_WORDS[form]} {arg}"


def _reducer(s: dict, grouped: bool) -> str:
    op, col = s["op"], s.get("column")
    each = " in each group" if grouped else ""
    return {
        "count": f"count the rows{each}",
        "count_missing": f"count the rows with no {col}{each}",
        "distinct": f"count the distinct values of {col}{each}",
        "sum": f"add up {col}{each} (exactly)",
        "mean": f"average {col}{each}, rounded to {MEAN_PLACES} decimal places",
        "max": f"take the largest {col}{each}",
        "min": f"take the smallest {col}{each}",
        "earliest": f"take the earliest {col}{each}",
        "latest": f"take the latest {col}{each}",
    }[op]


def explain(pipeline: list, table: str | None = None) -> str:
    """One sentence per step, joined; e.g. "Take every row of invoices; keep rows
    where status is 'paid'; add up amount (exactly)." """
    grouped = any(s["op"] == "group_by" for s in pipeline)
    parts = []
    for s in pipeline:
        op = s["op"]
        if op == "rows":
            parts.append(f"take every row of {table}" if table else "take every row")
        elif op == "filter":
            parts.append("keep rows where " + _filter(s))
        elif op == "join":
            how = s.get("how", "strict")
            head = f"look up each row's {s['on']} in {s['table']}.{s['to']}"
            parts.append(head + {
                "strict": " (every row must match, or the tool refuses)",
                "left": ", keeping rows with no match (their "
                        f"{s['table']} columns are empty)",
                "inner": ", leaving out rows with no match"}[how])
        elif op == "group_by":
            parts.append(f"group by {s['bucket']} of {s['column']}" if s.get("bucket")
                         else f"group by {s['column']}")
        elif op in REDUCERS:
            parts.append(_reducer(s, grouped))
        elif op == "top":
            first = "highest" if s.get("order", "desc") == "desc" else "lowest"
            parts.append(f"keep the top {s['n']} groups, {first} first "
                         f"(groups tied at the cutoff are all kept)")
    sentence = "; ".join(parts)
    return sentence[:1].upper() + sentence[1:] + "."
