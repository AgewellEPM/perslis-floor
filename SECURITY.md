# Security

## Keys

| key | purpose | where the public half lives |
|---|---|---|
| `perslis-floor-2026-09` (Ed25519) | signs tools (specs); the runtime trusts it via `floor_runtime/keys.py` | `floor_runtime/keys.py` |
| `releases@perslis.com` (ssh-ed25519) | signs `SHA256SUMS` of every release and founder kit | `perslis_signers`, this repo's README, perslis.com/perslis-floor.html |

The two keys are separate: a leaked release key cannot mint tools, and a
leaked tool key cannot fake a release. Secret halves never leave Perslis.

## What the signatures do and don't guarantee

- A valid tool signature means Perslis admitted that exact spec (and a person
  reviewed it). It does not stop the owner of a machine from editing the
  runtime. It protects you, not the code from you.
- A valid release signature means the zip is the one Perslis published.
  Verify it against the key published in at least two places above.

## Reporting a problem

Open a private security advisory on this repository (Security → Report a
vulnerability), or write to us through https://perslis.com/contact.html.
Please include the runtime version (`floor_runtime/__init__.py`) and, if you
can, the smallest data plus spec that shows the problem. Don't include real
customer data.
