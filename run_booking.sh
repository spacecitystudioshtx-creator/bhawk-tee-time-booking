#!/bin/bash
# run_booking.sh - Cron wrapper for the tee time booking bot
# This script is called by cron every Friday at 6:50 AM (before 7 AM booking window)
# It sets up the environment and runs book_tee_time.py with proper logging

set -euo pipefail

# Resolve the directory this script lives in
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
SCREENSHOT_DIR="$SCRIPT_DIR/screenshots"
TODAY=$(date +%Y-%m-%d)

# Ensure output directories exist
mkdir -p "$LOG_DIR" "$SCREENSHOT_DIR"

# Log file for this run (cron output + script output combined)
CRON_LOG="$LOG_DIR/cron_${TODAY}.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Cron job started ===" >> "$CRON_LOG"

# Activate virtual environment if it exists
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Activated virtual environment" >> "$CRON_LOG"
fi

# Set display for headless Chrome (in case Xvfb is running)
export DISPLAY=:99 2>/dev/null || true

# Run the booking script with headless mode enabled
cd "$SCRIPT_DIR"
HEADLESS=true python3 "$SCRIPT_DIR/book_tee_time.py" >> "$CRON_LOG" 2>&1
EXIT_CODE=$?

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Cron job finished (exit code: $EXIT_CODE) ===" >> "$CRON_LOG"

# Clean up old logs and screenshots (keep last 30 days)
find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true
find "$SCREENSHOT_DIR" -name "*.png" -mtime +30 -delete 2>/dev/null || true

exit $EXIT_CODE
