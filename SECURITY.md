# Security

## Keys

| key | purpose | where the public half lives |
|---|---|---|
| `perslis-floor-2026-09` (Ed25519) | signs tools (specs); the runtime trusts it via `floor_runtime/keys.py` | `floor_runtime/keys.py` |
| reviewer keys, e.g. `perslis-demo` (Ed25519) | sign the human approval every tool must carry | `floor_runtime/keys.py` (`REVIEWERS`) |
| `releases@perslis.com` (ssh-ed25519) | signs `SHA256SUMS` of every release and founder kit | `perslis_signers`, this repo's README, perslis.com/perslis-floor |

The keys are separate: a leaked release key cannot mint tools or approvals,
and a leaked tool key cannot fake a release or a reviewer. Secret halves never
leave Perslis.

## What the signatures do and don't guarantee

- A valid tool signature means Perslis admitted that exact spec; a valid
  reviewer attestation means an enrolled reviewer key approved exactly that
  spec, table, readback and answer. Neither stops the owner of a machine from
  editing the runtime: they protect you, not the code from you.
- A valid release signature means the files are the ones Perslis published.
  Verify it against the key published in at least two places above, and verify
  `install.sh` the same way before running it.

## Reporting a problem

Open a private security advisory on this repository (Security → Report a
vulnerability), or write to us through https://perslis.com/contact.html.
Please include the runtime version (`floor_runtime/__init__.py`) and, if you
can, the smallest data plus spec that shows the problem. Don't include real
customer data.
