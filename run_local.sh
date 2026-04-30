#!/bin/bash
# run_local.sh - Local Mac wrapper for the tee time booking bot
# Triggered by launchd on scheduled weekdays.
#
# Reliability hardening (don't strip without thinking):
#   1. caffeinate -dimsu wraps the python invocation so the Mac stays
#      awake (display, idle, disk, system) for the run. Mac mini is
#      AC-powered so -s actually applies.
#   2. pkill orphan Chromes using our bot's user-data-dir before launch,
#      so a previous hung run can't leave a profile lock that blocks the
#      next attempt.
#   3. osascript notification on failure — silent failure is the worst
#      outcome here, so make it loud.

# Note: no `set -e` — we want to send the failure notification even when
# the python step exits non-zero.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
SCREENSHOT_DIR="$SCRIPT_DIR/screenshots"
TODAY=$(date +%Y-%m-%d)

mkdir -p "$LOG_DIR" "$SCREENSHOT_DIR"

LOCAL_LOG="$LOG_DIR/local_${TODAY}.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Local booking run started ===" >> "$LOCAL_LOG"

# Kill any leftover Chrome instances holding our bot's profile lock.
# Targets only processes whose command line references .uc-bhcc-profile,
# so your normal browsing Chrome is untouched.
ORPHANS=$(pgrep -f "user-data-dir=.*\.uc-bhcc-profile" 2>/dev/null || true)
if [ -n "$ORPHANS" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Killing orphan Chrome PIDs: $ORPHANS" >> "$LOCAL_LOG"
    pkill -f "user-data-dir=.*\.uc-bhcc-profile" 2>/dev/null || true
    sleep 2
fi

if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/venv/bin/activate"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Activated virtual environment" >> "$LOCAL_LOG"
fi

cd "$SCRIPT_DIR"
# Visible browser — ezlinks blocks headless undetected-chromedriver with a
# perpetual "Please Wait..." spinner (verified 2026-04-30). The Mac must be
# awake and the user logged in so Chrome can get a rendering context.
# caffeinate keeps it that way for the duration of this script.
HEADLESS="${HEADLESS:-false}" caffeinate -dimsu python3 "$SCRIPT_DIR/book_tee_time.py" >> "$LOCAL_LOG" 2>&1
EXIT_CODE=$?

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Local booking run finished (exit code: $EXIT_CODE) ===" >> "$LOCAL_LOG"

# Loud failure notification. Silent failure = no tee time on Saturday.
if [ "$EXIT_CODE" -ne 0 ]; then
    LAST_LINE=$(tail -n 1 "$LOG_DIR/booking_${TODAY}.log" 2>/dev/null | tr -d '"' | cut -c1-180)
    osascript -e "display notification \"Booking FAILED (exit $EXIT_CODE). ${LAST_LINE:-See logs.}\" with title \"BHCC Tee Time Bot\" subtitle \"$(date '+%a %H:%M')\" sound name \"Funk\"" 2>/dev/null || true
else
    osascript -e "display notification \"Booking succeeded $(date '+%a %H:%M').\" with title \"BHCC Tee Time Bot\" sound name \"Glass\"" 2>/dev/null || true
fi

find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true
find "$SCREENSHOT_DIR" -name "*.png" -mtime +30 -delete 2>/dev/null || true

exit $EXIT_CODE
