#!/usr/bin/env bash
# Install / refresh the hourly cron entry that runs monitor.sh.
# Idempotent — running it twice yields the same crontab.

set -euo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
SCRIPT="$HERE/monitor.sh"
chmod +x "$SCRIPT" "$HERE/render.py"

MARKER="# reddit-saas-monitor"
LINE="0 * * * * $SCRIPT >> $HERE/data/cron.out 2>&1 $MARKER"

# Drop any previous entry, then append the new one.
( crontab -l 2>/dev/null | grep -v -F "$MARKER" || true; echo "$LINE" ) | crontab -

echo "Installed hourly cron entry:"
echo "  $LINE"
echo
echo "To verify:   crontab -l | grep reddit-saas-monitor"
echo "To uninstall: crontab -l | grep -v reddit-saas-monitor | crontab -"
