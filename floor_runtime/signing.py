"""Check that a spec is one Perslis admitted, unchanged. Verify only.

A signed spec file is an envelope:

    {"format": "perslis-floor-spec/1", "spec": {...}, "table": "invoices",
     "issued_to": "acme", "issued_at": "2026-09-26", "kid": "perslis-2026-09",
     "sig": "<ed25519 hex over the canonical envelope without 'sig'>"}

What this proves: the spec passed the Perslis admission gate and has not been
edited since. What it does not do: stop the owner of this machine from editing
this code. The runtime is a guarantee TO you about what you are running, not a
lock against you.
"""
from __future__ import annotations

import json

from . import ed25519
from .keys import TRUSTED

FORMAT = "perslis-floor-spec/1"


class SignatureError(ValueError):
    """Refused. A spec is loaded whole or not at all."""


def canonical(envelope: dict) -> bytes:
    body = {k: v for k, v in envelope.items() if k != "sig"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def require(envelope: dict, trusted: dict | None = None) -> dict:
    """Return the envelope if its signature checks out; raise otherwise."""
    keys = TRUSTED if trusted is None else trusted
    qc = (envelope.get("spec") or {}).get("question_class", "?")
    if envelope.get("format") != FORMAT:
        raise SignatureError(f"'{qc}': not a signed spec (format "
                             f"{envelope.get('format')!r}, expected {FORMAT!r})")
    kid, sig = envelope.get("kid"), envelope.get("sig")
    pub = keys.get(kid)
    if pub is None:
        raise SignatureError(f"'{qc}': signed by unknown key {kid!r}")
    try:
        ok = ed25519.verify(bytes.fromhex(pub), canonical(envelope), bytes.fromhex(sig or ""))
    except ValueError:
        ok = False
    if not ok:
        raise SignatureError(f"'{qc}': signature does not match — the spec was "
                             f"edited after admission, or not admitted at all")
    for key in ("spec", "table"):
        if not envelope.get(key):
            raise SignatureError(f"'{qc}': signed envelope has no '{key}'")
    return envelope
