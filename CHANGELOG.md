# Changelog

## 1.1.0 — 2026-09-26 · PILOT

**Vocabulary**
- `join`: a many-to-one lookup into another table. By default every row must
  match or the tool refuses; `"how": "left"` keeps unmatched rows and
  `"how": "inner"` drops them, and either choice is explicit and signed. A
  duplicate key on the lookup side is refused, because it would double-count.
- `group_by`, including `day` / `week` / `month` / `year` buckets for ISO
  dates.
- `top` ranks groups, and every group tied at the cutoff is returned.
- Filters: `in`, `contains`, and ISO date bounds (`after`, `before`,
  `on_or_after`, `on_or_before`).
- Reducers: `earliest`, `latest`.

**Exactness**
- Decimal arithmetic end to end, with no binary floats. Sums, minimums and
  maximums are exact; `mean` is rounded half-even to 10 places. A number or
  result beyond 38 significant digits (or exponent ±60) is refused.
- The following are refused by name instead of skipped: non-numbers in
  number positions, non-ISO dates, corrupt JSON rows, and files that change
  while being read.

**Data**
- CSV, TSV, JSON (numbers read as exact decimals), JSONL, SQLite (read-only),
  or a folder of them. The data is re-read when it changes on disk, and
  answers are cached until then.

**Trust**
- Tools are Ed25519-signed; the runtime holds only public keys. Each tool
  carries a person's review record (what it computes, its answer on the
  reviewed data, digests of the spec, table and data), covered by the
  signature.
- `SHA256SUMS` for releases and kits is signed with a separate release key
  (`ssh-keygen -Y verify`), whose public half is pinned outside the
  download. Builds are reproducible byte for byte.
- There is no option to add a trusted key from the command line.

**Operations**
- `report_gap`: questions no tool answers are recorded on the machine.
- Logs are split into shareable `tools/logs/` (no values, no question text)
  and private `tools/private/`.
- `floor-serve.py` works from any working directory, which suits MCP
  clients.

## 1.0.0 — 2026-09-25 · PROTOTYPE

- First runtime: `rows`, `filter` and seven reducers over JSON rows, served
  over MCP stdio, with HMAC-signed specs.
