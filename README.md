# Black Hawk Tee Time Booking (Mac Local)

This project is configured to run on your Mac with `launchd` and wake via `pmset`.

## Reliability Requirements (Important)

This runs as a macOS `LaunchAgent` (user GUI job). That means:

- The Mac must be powered on (sleep is OK, shutdown is not).
- Your user must be logged in. If you fully sign out, LaunchAgents do not run.
- Locking the screen is OK.

## Current Automation Setup

- LaunchAgent: `/Users/alexdimitroff/Library/LaunchAgents/com.alexdimitroff.bhawk-tee-time.plist`
- Script path: `/Users/alexdimitroff/Space-City-Studios/bhawk-tee-time-booking/run_local.sh`
- Schedule:
  - Thursday at `06:50`
  - Friday at `06:50`
- Booking logic:
  - Bot always books `+8 days` from run date.
  - Thursday run targets Friday tee times.
  - Friday run targets Saturday tee times.
  - Search clicks at/after `7:00 AM`, then filters by configured time windows.

## Time Windows

Configured in `/Users/alexdimitroff/Space-City-Studios/bhawk-tee-time-booking/booking_config.json`:

- Friday target date window: `7:00` to `18:00`
- Saturday target date window: `9:00` to `18:00`

`target_dates` is for one-off manual dates.

## Key Files

- Main bot: `/Users/alexdimitroff/Space-City-Studios/bhawk-tee-time-booking/book_tee_time.py`
- Local wrapper: `/Users/alexdimitroff/Space-City-Studios/bhawk-tee-time-booking/run_local.sh`
- Config: `/Users/alexdimitroff/Space-City-Studios/bhawk-tee-time-booking/booking_config.json`
- Logs: `/Users/alexdimitroff/Space-City-Studios/bhawk-tee-time-booking/logs`
- Screenshots: `/Users/alexdimitroff/Space-City-Studios/bhawk-tee-time-booking/screenshots`

## Useful Commands

Check scheduler details:

```bash
launchctl print gui/$(id -u)/com.alexdimitroff.bhawk-tee-time
pmset -g sched
```

## Python Environment (Avoid "new Python broke it")

Use the project virtualenv so system Python updates do not break dependencies.

Create/install:

```bash
cd /Users/alexdimitroff/Space-City-Studios/bhawk-tee-time-booking
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install setuptools
```

Run manually now (normal mode):

```bash
cd /Users/alexdimitroff/Space-City-Studios/bhawk-tee-time-booking
source venv/bin/activate
HEADLESS=false python3 book_tee_time.py
```

Run manually for testing a different lead time (example `+6` days):

```bash
cd /Users/alexdimitroff/Space-City-Studios/bhawk-tee-time-booking
source venv/bin/activate
HEADLESS=false DAYS_AHEAD=6 python3 book_tee_time.py
```

## Notes

- Today (Thu Feb 12, 2026), a live manual run successfully completed a reservation for Wed Feb 18, 2026.
- If booking fails, check latest logs/screenshots first; checkout flow can vary and selectors may need minor updates.
