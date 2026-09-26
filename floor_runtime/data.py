"""Load evidence from the files people actually have. Standard library only.

    .json                 {"table": [ {col: value}, ... ]}  or a top-level list of rows
    .jsonl                one JSON row per line              (table = file stem)
    .csv / .tsv           header row, then rows              (table = file stem)
    .sqlite .sqlite3 .db  every table and view, opened read-only
    a directory           every supported file directly inside it

Values are kept as they arrive — CSV cells stay strings, SQLite keeps its
types, JSON numbers are read as exact decimals (never binary floats). The
executor parses numbers and dates itself and refuses what it cannot parse, so
nothing is coerced silently here. Every table entry must be a row (an object);
a corrupt entry fails the whole load rather than being skipped.

Postgres, MySQL and the rest have no standard-library driver. Export the
tables you care about to CSV (or a SQLite file) and point at that.
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import time
from decimal import Decimal
from pathlib import Path

MAX_ROWS = 1_000_000      # total across tables. Measured: 500k rows = ~400 MB RSS,
                          # ~2 s per uncached query on an M-series laptop.
_TABLE_EXT = {".csv", ".tsv", ".jsonl"}
_SQLITE_EXT = {".sqlite", ".sqlite3", ".db"}
SUPPORTED = _TABLE_EXT | _SQLITE_EXT | {".json"}


class LoadError(ValueError):
    """The evidence could not be read whole. Nothing partial is served."""


def _csv_rows(path: Path) -> list:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        head = fh.readline()
        fh.seek(0)
        if path.suffix.lower() == ".tsv":
            delim = "\t"
        else:
            delim = ";" if head.count(";") > head.count(",") else ","
        reader = csv.reader(fh, delimiter=delim)
        try:
            header = next(reader)
        except StopIteration:
            raise LoadError(f"{path.name}: empty file") from None
        header = [h.strip() for h in header]
        if any(not h for h in header):
            raise LoadError(f"{path.name}: a header cell is empty")
        dupes = sorted({h for h in header if header.count(h) > 1})
        if dupes:
            raise LoadError(f"{path.name}: duplicate header(s) {dupes}")
        rows = []
        for n, cells in enumerate(reader, start=2):
            if not cells:
                continue
            if any("\x00" in c for c in cells):      # py<3.11 raises, newer passes it
                raise LoadError(f"{path.name}: line {n} contains NUL bytes — "
                                f"not a text export")
            if len(cells) > len(header):
                raise LoadError(f"{path.name}: line {n} has {len(cells)} cells, "
                                f"header has {len(header)}")
            rows.append({h: (cells[i] if i < len(cells) else None)
                         for i, h in enumerate(header)})
        return rows


def _jsonl_rows(path: Path) -> list:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line, parse_float=Decimal)
            except ValueError as exc:
                raise LoadError(f"{path.name}: line {n} is not JSON ({exc})") from None
            if not isinstance(row, dict):
                raise LoadError(f"{path.name}: line {n} is not an object")
            rows.append(row)
    return rows


def _require_rows(path: Path, table: str, rows: list) -> list:
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            raise LoadError(f"{path.name}: table '{table}' entry {i} is not a row "
                            f"(an object) — the file is corrupt or not a table")
    return rows


def _json_tables(path: Path) -> dict:
    try:
        blob = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except ValueError as exc:
        raise LoadError(f"{path.name}: not JSON ({exc})") from None
    if isinstance(blob, list):
        return {path.stem: _require_rows(path, path.stem, blob)}
    if isinstance(blob, dict):
        tables = {k: _require_rows(path, k, v) for k, v in blob.items() if isinstance(v, list)}
        if not tables:
            raise LoadError(f"{path.name}: no tables (expected {{name: [rows]}})")
        return tables
    raise LoadError(f"{path.name}: expected an object of tables or a list of rows")


def _sqlite_tables(path: Path) -> dict:
    uri = f"file:{path.resolve()}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise LoadError(f"{path.name}: {exc}") from None
    try:
        con.row_factory = sqlite3.Row
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        out = {}
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            out[name] = [dict(r) for r in con.execute(f"SELECT * FROM {quoted}")]
        return out
    except sqlite3.Error as exc:
        raise LoadError(f"{path.name}: {exc}") from None
    finally:
        con.close()


def _load_file(path: Path, table: str | None) -> dict:
    ext = path.suffix.lower()
    if ext in (".csv", ".tsv"):
        return {table or path.stem: _csv_rows(path)}
    if ext == ".jsonl":
        return {table or path.stem: _jsonl_rows(path)}
    if ext == ".json":
        tables = _json_tables(path)
        if table and len(tables) == 1:
            return {table: next(iter(tables.values()))}
        return tables
    if ext in _SQLITE_EXT:
        return _sqlite_tables(path)
    raise LoadError(f"{path.name}: unsupported type {ext or '(none)'} — "
                    f"use one of {sorted(SUPPORTED)}")


def _files(path: Path) -> list:
    if path.is_dir():
        return sorted(p for p in path.iterdir()
                      if p.is_file() and p.suffix.lower() in SUPPORTED)
    return [path]


def load(path, table: str | None = None, max_rows: int = MAX_ROWS) -> dict:
    """{table: [rows]} from a file or directory. Raises LoadError, never partial."""
    p = Path(path)
    if not p.exists():
        raise LoadError(f"no such file or directory: {p}")
    files = _files(p)
    if not files:
        raise LoadError(f"{p}: no supported files ({sorted(SUPPORTED)})")
    ctx: dict = {}
    for f in files:
        try:
            tables = _load_file(f, table if not p.is_dir() else None)
        except UnicodeDecodeError:
            raise LoadError(f"{f.name}: not UTF-8 text — re-export it as UTF-8 "
                            f"(in Excel: 'CSV UTF-8')") from None
        except csv.Error as exc:
            raise LoadError(f"{f.name}: malformed CSV ({exc})") from None
        except OSError as exc:
            raise LoadError(f"{f.name}: cannot read ({exc.strerror or exc})") from None
        for name, rows in tables.items():
            if name in ctx:
                raise LoadError(f"table '{name}' is defined twice (second in {f.name})")
            ctx[name] = rows
    total = sum(len(v) for v in ctx.values())
    if total > max_rows:
        raise LoadError(f"{total} rows is over the {max_rows} limit — "
                        f"export a narrower slice or raise --max-rows")
    return ctx


def fingerprint(path) -> tuple:
    """Changes whenever the evidence on disk changes (incl. SQLite WAL files).

    Inode and change-time are included: a replacement that keeps the size and
    restores the modification time (cp -p, rsync -t) still changes ctime, which
    users cannot set."""
    p = Path(path)
    out = []
    for f in _files(p) if p.exists() else []:
        for side in (f, Path(str(f) + "-wal")):
            try:
                st = os.stat(side)
                out.append((str(side), st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns))
            except FileNotFoundError:
                pass
    return tuple(out)


def load_stable(path, table: str | None = None, max_rows: int = MAX_ROWS,
                attempts: int = 3) -> tuple[dict, tuple]:
    """(ctx, fingerprint) for a snapshot that did not change while it was read.

    The fingerprint is taken before and after loading; a mismatch means the
    export was being written (or a multi-file export was half-replaced), so the
    read is retried and finally refused — never cached as a mixture."""
    for i in range(attempts):
        before = fingerprint(path)
        ctx = load(path, table, max_rows)
        if fingerprint(path) == before:
            return ctx, before
        time.sleep(0.05 * (i + 1))
    raise LoadError("the data kept changing while it was being read — "
                    "try again when the export has finished writing")


class DataSource:
    """Evidence that follows the file. Reloads when it changes on disk; if a
    changed file cannot be read, it raises rather than serving stale data."""

    def __init__(self, path, table: str | None = None, max_rows: int = MAX_ROWS):
        self.path, self.table, self.max_rows = Path(path), table, max_rows
        self._ctx, self._fp = load_stable(self.path, table, max_rows)
        self.version = 0          # bumps on every successful reload

    def get(self) -> dict:
        if fingerprint(self.path) != self._fp:
            self._ctx, self._fp = load_stable(self.path, self.table, self.max_rows)
            self.version += 1
        return self._ctx
