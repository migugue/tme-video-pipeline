#!/usr/bin/env bash
# Launch Chrome with the remote debugging port the recorder attaches to.
# Uses a dedicated profile so your normal browsing session is unaffected.
#
# Usage:
#   ./start_chrome.sh                # defaults to port 9333, profile .tme-chrome-profile
#   TME_CDP_PORT=9222 ./start_chrome.sh
#
# After it launches, log into whatever app you want to record (Aruba Central,
# VALID8, etc.) and leave the window visible before running /video-record.

set -euo pipefail

PORT="${TME_CDP_PORT:-9333}"
PROFILE_DIR="${TME_CHROME_PROFILE:-$HOME/.tme-chrome-profile}"
CHROME="${TME_CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

if [ ! -x "$CHROME" ]; then
  echo "Chrome not found at: $CHROME" >&2
  echo "Install Google Chrome Stable or set TME_CHROME_BIN." >&2
  exit 1
fi

mkdir -p "$PROFILE_DIR"

echo "Launching Chrome on debug port $PORT"
echo "  profile: $PROFILE_DIR"
echo "  (close this terminal to quit Chrome, or Cmd+Q the window)"

exec "$CHROME" \
  --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run \
  --no-default-browser-check
