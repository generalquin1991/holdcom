#!/usr/bin/env bash
#
# holdcom installer — single-file, pure-stdlib. No pip / no compilation needed.
#
# One-liner (after the repo is hosted on GitHub):
#   curl -fsSL https://raw.githubusercontent.com/generalquin1991/holdcom/main/install.sh | bash
#
# Or run locally from a checked-out repo:
#   bash install.sh
#
# Override the source URL with HOLDCOM_URL if you host it elsewhere:
#   HOLDCOM_URL=https://example.com/holdcom.py bash install.sh

set -euo pipefail

INSTALL_NAME="holdcom"

# Default source: GitHub raw. Replace generalquin1991 once the repo is pushed.
DEFAULT_URL="https://raw.githubusercontent.com/generalquin1991/holdcom/main/holdcom.py"
HOLDCOM_URL="${HOLDCOM_URL:-$DEFAULT_URL}"

# Choose an install dir: prefer /usr/local/bin if writable, else ~/bin.
if [ -w /usr/local/bin ]; then
  BIN="/usr/local/bin"
elif [ -d "$HOME/bin" ]; then
  BIN="$HOME/bin"
else
  BIN="$HOME/bin"
  mkdir -p "$BIN"
fi

echo ">> holdcom installer"
echo "   source : $HOLDCOM_URL"
echo "   target : $BIN/$INSTALL_NAME"

TMP="$(mktemp "${TMPDIR:-/tmp}/holdcom.XXXXXX")"
cleanup() { rm -f "$TMP"; }
trap cleanup EXIT

echo ">> downloading…"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$HOLDCOM_URL" -o "$TMP"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$TMP" "$HOLDCOM_URL"
else
  echo "!! neither curl nor wget found; install one and retry" >&2
  exit 1
fi

# Sanity: must be a python script with a shebang.
if ! head -1 "$TMP" | grep -q 'python3'; then
  echo "!! downloaded file does not look like holdcom.py (missing python3 shebang); aborting" >&2
  exit 1
fi

install -m 0755 "$TMP" "$BIN/$INSTALL_NAME"
echo ">> installed: $BIN/$INSTALL_NAME"

# Smoke test.
if command -v "$INSTALL_NAME" >/dev/null 2>&1; then
  "$INSTALL_NAME" selftest || echo "!! selftest reported a problem; check python3 on PATH"
else
  echo "!! $INSTALL_NAME not found on PATH after install; add $BIN to PATH"
fi

echo ">> done. try: holdcom --help"
