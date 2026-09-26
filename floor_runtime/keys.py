"""Public keys this runtime trusts, by key id. Public — safe to ship and read.

A spec signed by any other key is refused. Rotation: add the new key here and
cut a release; remove a key to stop trusting everything it signed.
"""
TRUSTED: dict[str, str] = {
    # Perslis floor signing key, generated 2026-09-26. Secret held off-repo.
    "perslis-floor-2026-09":
        "e4a2225d46e9afaa196714079e8596c3d7323b7633730fe8e0069a86f98835c5",
}
