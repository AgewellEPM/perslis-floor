"""Public keys this runtime trusts, by key id. Public — safe to ship and read.

TRUSTED signs specs (tools); REVIEWERS sign the human approval each tool must
carry. A spec signed by any other key, or approved by any other reviewer key,
is refused. Rotation: add the new key here and cut a release; remove a key to
stop trusting everything it signed.
"""
TRUSTED: dict[str, str] = {
    # Perslis floor signing key, generated 2026-09-26. Secret held off-repo.
    "perslis-floor-2026-09":
        "e4a2225d46e9afaa196714079e8596c3d7323b7633730fe8e0069a86f98835c5",
}

# Reviewers whose signed approvals this runtime accepts. The public release
# ships only the demo reviewer; founder kits carry the reviewers of their tools.
REVIEWERS: dict[str, str] = {
    # Machine review of the public demo: every demo answer was checked against an
    # independently computed expected answer before this key signed the approval.
    "perslis-demo":
        "38e23d6e325c9ce411effcf949c9967ff2bd47befb8e216b85aa05267e6b5187",
}
