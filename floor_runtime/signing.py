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

import hashlib
import json

from . import ed25519
from .keys import REVIEWERS, TRUSTED

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


# ─────────────────────── reviewer attestations ───────────────────────────
# Every tool must carry a person's approval, and that approval is itself signed
# with the reviewer's own key. A review record anyone could recompute (hashes,
# readback, answer) proves nothing on its own; the attestation proves which
# enrolled reviewer approved exactly this spec, table, readback and answer.

REVIEW_FIELDS = ("by", "at", "readback", "answer_on_evidence", "evidence_sha256",
                 "spec_sha256", "attestation")


def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def review_digest(spec: dict, table: str) -> str:
    """What a review approves: the exact spec AND the table it runs over."""
    return hashlib.sha256(_canon({"spec": spec, "table": table})).hexdigest()


def review_payload(review: dict) -> bytes:
    """The bytes a reviewer signs: the whole record except the attestation."""
    return _canon({k: v for k, v in review.items() if k != "attestation"})


def require_review(envelope: dict, reviewers: dict | None = None) -> dict:
    """The envelope's review, if an enrolled reviewer really signed it; raise otherwise."""
    keys = REVIEWERS if reviewers is None else reviewers
    qc = (envelope.get("spec") or {}).get("question_class", "?")
    review = envelope.get("review")
    if not isinstance(review, dict):
        raise SignatureError(f"'{qc}': no reviewer attestation — every tool needs a "
                             f"person's signed approval")
    missing = [f for f in REVIEW_FIELDS if f not in review]
    if missing:
        raise SignatureError(f"'{qc}': review record incomplete (missing {missing})")
    att = review["attestation"]
    rid = att.get("reviewer") if isinstance(att, dict) else None
    pub = keys.get(rid)
    if pub is None:
        raise SignatureError(f"'{qc}': reviewed with an unknown reviewer key {rid!r}")
    try:
        ok = ed25519.verify(bytes.fromhex(pub), review_payload(review),
                            bytes.fromhex(att.get("sig") or ""))
    except ValueError:
        ok = False
    if not ok:
        raise SignatureError(f"'{qc}': reviewer attestation does not match — the review "
                             f"record was edited or forged")
    if review["spec_sha256"] != review_digest(envelope.get("spec"), envelope.get("table")):
        raise SignatureError(f"'{qc}': the review approves a different spec or table")
    return review
