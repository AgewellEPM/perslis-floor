<div align="center">

# ⬦ Perslis Floor

### Exact answers from your own data, with no model in the loop.

Ask a question about your data once. Get back a **signed tool** that your AI
assistant can call from then on. It runs offline and free, and when the data
can't support an exact answer, it **refuses rather than guessing**.

![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)
![Dependencies](https://img.shields.io/badge/dependencies-none%20%C2%B7%20stdlib-79c0a0)
![Network](https://img.shields.io/badge/network-none-555)
![MCP](https://img.shields.io/badge/MCP-stdio-8a63d2)
![Status](https://img.shields.io/badge/status-1.1.0%20%C2%B7%20pilot-e0a800)

English · [中文](README.zh.md)

</div>

---

## Install

**One line.** It downloads the signed release, verifies it, unpacks it to
`~/perslis-floor` and runs the demo:

```bash
curl -fsSL https://raw.githubusercontent.com/AgewellEPM/perslis-floor/main/install.sh | bash
```

**Or by hand.** Download `perslis-floor-1.1.0.zip`, `SHA256SUMS` and
`SHA256SUMS.sig` from the [latest release](https://github.com/AgewellEPM/perslis-floor/releases/latest),
then verify before you unzip:

```bash
echo 'releases@perslis.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJfmXcRm2o52skHrajOCntbGMwPIB13CWnzt/tRGxXxd' > perslis_signers
ssh-keygen -Y verify -f perslis_signers -I releases@perslis.com -n perslis-release -s SHA256SUMS.sig < SHA256SUMS
shasum -a 256 -c SHA256SUMS
unzip perslis-floor-1.1.0.zip && cd perslis-floor-1.1.0
```

That release key is also published at
[perslis.com/perslis-floor](https://perslis.com/perslis-floor.html). Compare
the two copies: a key that appears in only one place proves nothing. Every file
inside the zip is listed in `MANIFEST.sha256` (`shasum -a 256 -c MANIFEST.sha256`).

## 60-second demo

The download includes fictional invoice and vendor data, plus six tools that
Perslis admitted, reviewed against independently computed answers, and signed:

```bash
python3 floor-serve.py --data demo/data --tools demo/tools --check
```

```
DERIVED     derive_demo_invoices_missing_po  ->  7
DERIVED     derive_demo_invoices_per_month  ->  {"2026-01": 6, "2026-02": 6, ...}
DERIVED     derive_demo_largest_open_invoice  ->  4901.45
DERIVED     derive_demo_paid_by_region  ->  {"Central": 11215.45, "East": 21576.59, ...}
DERIVED     derive_demo_paid_total  ->  70588.31
DERIVED     derive_demo_top_vendors_by_invoiced  ->  [["Harbor Tool Co", 36308.95], ...]
```

Connect it to Claude Code and ask in plain English:

```bash
claude mcp add perslis-floor-demo -- python3 "$PWD/floor-serve.py" \
    --data "$PWD/demo/data" --tools "$PWD/demo/tools"
```

> *"How much have we paid, by vendor region?"*

Claude calls the tool and gets back the exact answer, together with the
procedure that produced it:

```json
{"status": "DERIVED", "value": {"Central": 11215.45, "East": 21576.59, "South": 4800.25, "West": 32996.02},
 "model_calls": 0,
 "derivation": "rows -> filter(status equals 'paid') -> join(vendors on vendor_id=id) -> group_by(vendors.region) -> sum(amount)"}
```

Ask something no tool covers, like *"what's our churn rate?"*, and it says so
and records the question on your machine. It does not make up a number.

## How it works

```
 your question ──▶ a model writes a SPEC ──▶ the admission gate ──▶ a person reviews ──▶ signed tool
   (English)       (a pipeline, not code)     (8 checks)             (readback + answer)    (runs on your machine)
```

1. **The model writes a spec, never code.** It composes a pipeline from a
   closed vocabulary, such as `rows → filter → join → group_by → sum`. There is
   no way out of that vocabulary into Python.
2. **The gate proves the spec.** It checks that every named column exists, the
   data supports an exact answer, and the result is deterministic. It checks
   that the verifier *rejects* wrong answers, the spec abstains when there's no
   evidence, and the answer moves when the data does, so it can't be a
   memorised constant.
3. **A person approves it.** The gate can prove a spec is correct as written.
   It can't prove the spec means what the question means (a spec for "total
   paid" that filters `status == 'open'` passes every mechanical check). So a
   reviewer reads what the tool computes in plain words, next to its answer on
   the real data, before signing. That approval is recorded inside the tool.
4. **You run it.** This runtime checks the Ed25519 signature and serves the tool
   over MCP. Every answer carries `model_calls: 0` and its derivation.

## What a tool can compute

```
rows  (filter | join)*  [group_by]  reducer  [top]
```

| step | forms |
|---|---|
| `filter` | `equals` · `not_equals` · `in` · `contains` · `empty` · `nonempty` · `gt` `gte` `lt` `lte` · `after` `before` `on_or_after` `on_or_before` (ISO dates) |
| `join` | many-to-one lookup into another table. By default **every row must match**; keeping (`left`) or leaving out (`inner`) unmatched rows must be explicit |
| `group_by` | a column, or a date bucketed by `day` / `week` / `month` / `year` |
| reducers | `count` · `count_missing` · `distinct` · `sum` · `mean` · `max` · `min` · `earliest` · `latest` |
| `top` | rank the groups; groups tied at the cutoff are all returned |

Arithmetic is **exact decimal**, with no floating point: `9007199254740992 + 1`
is `9007199254740993`. Only `mean` rounds (half-even, 10 decimal places).

**Data:** `.csv` `.tsv` `.json` `.jsonl` `.sqlite`, or a folder of them. Each
file is a table. The data is re-read when it changes on disk.

## What it will not do

- **Guess.** No evidence gives `NO_EVIDENCE`, and no matching rows gives
  `NO_VALUE`.
- **Answer from data it can't trust.** You get `REFUSED`, with the reason, for:
  - `N/A` in a number column;
  - `03/04/2026` in a date column (March or April?);
  - a lookup key that appears twice (it would double-count);
  - a row with no match in a lookup (it would silently undercount);
  - a corrupt JSON row;
  - a file that's still being written.
- **Run a tool Perslis didn't admit.** Edit a signed tool and the runtime
  refuses it by name and serves the rest. The runtime holds only public keys,
  so it can check signatures but can't create them. This protects you: you know
  exactly what you're running. It is not a lock against you, since the source
  is right here.
- **Phone home.** `grep -rnE "socket|urllib|http|requests" floor_runtime/`
  finds nothing. The local logs are split:
  - `tools/logs/` is shareable. It records which tools ran and refusal reasons
    without values, plus a fingerprint for each unanswered question.
  - `tools/private/` is yours. It holds the question text.

## Getting tools for your own data

The admission gate and the signing keys stay at Perslis. That's deliberate: a
wrong spec that got signed would answer confidently, offline and forever, with
nothing left to re-examine it. In the current pilot the flow is:

1. You send an export and your questions.
2. We build the tools, review each one and sign them.
3. You get a kit: this runtime, your tools, and a guide.

→ **[perslis.com/contact](https://perslis.com/contact.html)**

## Status

**PILOT, version 1.1.0.** It's tested end to end, including a real MCP client
calling a built kit, on Python 3.9 (the macOS default) and 3.13. Measured on an
M-series laptop at 500k rows (an 18 MB CSV): about 1.3 s to load, about 400 MB
of RAM, and about 2.3 s for the first query after the data changes. Repeat
answers are instant.

Known limits:

- no relative dates ("last 30 days");
- no parameterised tools (one tool per question);
- everything is held in memory, 1M rows by default;
- no direct database connections: export to CSV or SQLite.

## License

Source-available. You may use it free of charge, including commercially, to run
tools admitted by Perslis. You may not pass modified copies off as the Perslis
runtime, or claim that a spec was admitted when it wasn't. The admission gate is
not included. See [`LICENSE.txt`](LICENSE.txt).

<sub>Perslis Research · <a href="https://perslis.com">perslis.com</a></sub>
