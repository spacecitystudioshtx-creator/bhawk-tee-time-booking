#!/bin/bash
# run_local.sh - Local Mac wrapper for the tee time booking bot
# Triggered by launchd daily at 6:50 AM after pmset wakes the Mac at 6:45 AM.
# Only books if today + 8 days matches a scheduled date in booking_config.json.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
SCREENSHOT_DIR="$SCRIPT_DIR/screenshots"
TODAY=$(date +%Y-%m-%d)

mkdir -p "$LOG_DIR" "$SCREENSHOT_DIR"

CRON_LOG="$LOG_DIR/local_${TODAY}.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Local booking run started ===" >> "$CRON_LOG"

# Activate virtual environment
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Activated virtual environment" >> "$CRON_LOG"
fi

# Run the booking script
cd "$SCRIPT_DIR"
# Non-headless required: Cloudflare blocks headless Chrome on ezlinksgolf.com
HEADLESS=false python3 "$SCRIPT_DIR/book_tee_time.py" >> "$CRON_LOG" 2>&1
EXIT_CODE=$?

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Local booking run finished (exit code: $EXIT_CODE) ===" >> "$CRON_LOG"

# Clean up old logs and screenshots (keep last 30 days)
find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true
find "$SCREENSHOT_DIR" -name "*.png" -mtime +30 -delete 2>/dev/null || true

exit $EXIT_CODE
