#!/usr/bin/env bash
# Install Perslis Floor: download the signed release, verify it, unpack it, run the demo.
#
#   curl -fsSL https://raw.githubusercontent.com/AgewellEPM/perslis-floor/main/install.sh | bash
#
# Refuses to install unless SHA256SUMS carries a valid signature from the
# Perslis release key below AND the zip matches it. Installs into
# ~/perslis-floor (override with PERSLIS_FLOOR_HOME); never overwrites.
# The same key is published at https://perslis.com/perslis-floor.html —
# compare the two if you want a second channel.
set -euo pipefail

REPO="AgewellEPM/perslis-floor"
VERSION="${PERSLIS_FLOOR_VERSION:-1.1.0}"
DEST="${PERSLIS_FLOOR_HOME:-$HOME/perslis-floor}"
SIGNER='releases@perslis.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJfmXcRm2o52skHrajOCntbGMwPIB13CWnzt/tRGxXxd'
# A mirror may serve the files; the signature check below still decides.
BASE="${PERSLIS_FLOOR_BASE_URL:-https://github.com/$REPO/releases/download/v$VERSION}"
ZIP="perslis-floor-$VERSION.zip"

say()  { printf '%s\n' "$*"; }
fail() { printf '✗ %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "needs '$1' on PATH"; }

need curl; need unzip; need ssh-keygen; need python3
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || fail "needs Python 3.9 or newer (python3 --version)"
[ -e "$DEST" ] && fail "$DEST already exists — move it, or set PERSLIS_FLOOR_HOME"

WORK="$(mktemp -d)"
cleanup() { [ -n "${WORK:-}" ] && [ -d "$WORK" ] && rm -r "$WORK"; }
trap cleanup EXIT

say "▸ Downloading Perslis Floor $VERSION"
for f in "$ZIP" SHA256SUMS SHA256SUMS.sig; do
  curl -fsSL -o "$WORK/$f" "$BASE/$f" || fail "could not download $f from $BASE"
done

say "▸ Verifying the release signature"
printf '%s\n' "$SIGNER" > "$WORK/perslis_signers"
ssh-keygen -Y verify -f "$WORK/perslis_signers" -I releases@perslis.com \
  -n perslis-release -s "$WORK/SHA256SUMS.sig" < "$WORK/SHA256SUMS" >/dev/null 2>&1 \
  || fail "signature check FAILED — this is not a Perslis release. Nothing was installed."

say "▸ Verifying the checksum"
if command -v shasum >/dev/null 2>&1; then
  (cd "$WORK" && shasum -a 256 -c SHA256SUMS >/dev/null) || fail "checksum FAILED"
else
  (cd "$WORK" && sha256sum -c SHA256SUMS >/dev/null) || fail "checksum FAILED"
fi

say "▸ Installing to $DEST"
(cd "$WORK" && unzip -q "$ZIP")
mv "$WORK/perslis-floor-$VERSION" "$DEST"

say "▸ Running the demo"
python3 "$DEST/floor-serve.py" --data "$DEST/demo/data" --tools "$DEST/demo/tools" --check

cat <<EOF

✓ Perslis Floor $VERSION is installed in $DEST

Connect the demo to Claude Code:
  claude mcp add perslis-floor-demo -- python3 "$DEST/floor-serve.py" \\
      --data "$DEST/demo/data" --tools "$DEST/demo/tools"

Then ask: "How much have we paid, by vendor region?"
Tools for your own data: https://perslis.com/contact.html
EOF
