#!/usr/bin/env bash
# One-shot environment check + install. Called by the video-bootstrap skill, or
# runnable standalone for a quick sanity check.
#
# Usage:
#   ./bootstrap.sh         # install into ./.venv in the current folder
#   ./bootstrap.sh --check # just report env status, don't install

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

green() { printf '\033[32m%s\033[0m' "$1"; }
red()   { printf '\033[31m%s\033[0m' "$1"; }
dim()   { printf '\033[2m%s\033[0m' "$1"; }

say_ok()   { echo "  $(green '✓') $1"; }
say_fail() { echo "  $(red '✗') $1"; }

echo "tme-video-pipeline — environment check"
echo

# Chrome
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ -x "$CHROME" ]; then
  say_ok "Chrome Stable"
else
  say_fail "Chrome Stable not found (install from https://www.google.com/chrome/)"
fi

# Python
if command -v python3 >/dev/null; then
  PV="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
  PV_MAJ="$(python3 -c 'import sys; print(sys.version_info[0])')"
  PV_MIN="$(python3 -c 'import sys; print(sys.version_info[1])')"
  if [ "$PV_MAJ" -ge 3 ] && [ "$PV_MIN" -ge 11 ]; then
    say_ok "Python $PV"
  else
    say_fail "Python $PV found — need 3.11 or later"
  fi
else
  say_fail "python3 not found"
fi

# Zoe Premium voice (optional but default)
if command -v say >/dev/null; then
  if say -v '?' 2>/dev/null | grep -qi 'Zoe.*Premium\|Zoe (Premium)'; then
    say_ok "Zoe Premium voice"
  else
    say_fail "Zoe Premium voice not installed"
    echo "    $(dim 'Download it via System Settings → Accessibility → Spoken Content → System Voice → Manage Voices')"
  fi
else
  say_fail "say command not found (not on macOS?)"
fi

if [ "$CHECK_ONLY" = 1 ]; then
  exit 0
fi

echo
echo "Setting up project venv..."

cd "$(pwd)"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# Honor HTTPS_PROXY if set — pip will pick it up automatically from env
if [ -n "${HTTPS_PROXY:-}" ] || [ -n "${https_proxy:-}" ]; then
  echo "  $(dim 'using proxy'): ${HTTPS_PROXY:-$https_proxy}"
fi

.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r "$ROOT/requirements.txt" --quiet

say_ok "project venv at .venv/ with dependencies installed"

echo
echo "Done. Next: in Claude Code, run /video-new to script your first recording."
