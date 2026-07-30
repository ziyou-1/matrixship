#!/usr/bin/env bash
set -euo pipefail
DISPLAY_NUM="${DISPLAY_NUM:-:99}"
DISPLAY_IDX="${DISPLAY_NUM#:}"
# Wait for the Xvfb display created by matrix-node-api.service.
for i in $(seq 1 120); do
  if [ -S "/tmp/.X11-unix/X${DISPLAY_IDX}" ]; then
    break
  fi
  sleep 1
done
# Prefer the Xauthority file used by the currently running Xvfb process.
AUTH_FILE=""
for i in $(seq 1 30); do
  AUTH_FILE="$(ps -eo args | awk -v d="$DISPLAY_NUM" '$0 ~ ("Xvfb " d) { for (i=1;i<=NF;i++) if ($i=="-auth") {print $(i+1); exit} }')"
  if [ -n "$AUTH_FILE" ] && [ -f "$AUTH_FILE" ]; then
    break
  fi
  sleep 1
done
# Fallback to the newest xvfb-run Xauthority if process parsing failed.
if [ -z "$AUTH_FILE" ] || [ ! -f "$AUTH_FILE" ]; then
  AUTH_FILE="$(ls -t /tmp/xvfb-run.*/Xauthority 2>/dev/null | head -n 1 || true)"
fi
if [ -n "$AUTH_FILE" ] && [ -f "$AUTH_FILE" ]; then
  echo "Using Xauthority: $AUTH_FILE" >&2
  exec /usr/bin/x11vnc -display "$DISPLAY_NUM" -auth "$AUTH_FILE" -localhost -forever -shared -rfbport 5900 -noxdamage -repeat -nopw -quiet
fi
echo "Using x11vnc -auth guess for $DISPLAY_NUM" >&2
exec /usr/bin/x11vnc -display "$DISPLAY_NUM" -auth guess -localhost -forever -shared -rfbport 5900 -noxdamage -repeat -nopw -quiet
