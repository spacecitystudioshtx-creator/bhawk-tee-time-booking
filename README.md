# Black Hawk Tee Time Booking (Mac Local)

Automated tee time booking for Black Hawk Country Club. Runs headless via `launchd` — works even when the laptop is locked or the lid is closed.

## How It Works

- LaunchAgent fires at **6:50 AM** on Thursdays and Fridays
- Bot logs in, navigates to the booking page, fills in the target date (+8 days ahead)
- Waits until exactly **7:00 AM** (when tee times open), then clicks Search
- If no times show up in the window, keeps re-running the search (every ~10s, for up to 30 min) — right at the drop the site often lags and inventory posts late, so a single search can come back "0 tee times"
- Selects the first available time in the configured window and completes the reservation

## Schedule

| Run Day   | Targets       | Time Window  |
|-----------|---------------|--------------|
| Thursday  | Next Friday   | 12:00 - 1:00 PM |
| Friday    | Next Saturday | 12:00 - 1:00 PM |

Time windows are configured in `booking_config.json`.

## Key Files

| File | Purpose |
|------|---------|
| `book_tee_time.py` | Main booking automation |
| `run_local.sh` | Shell wrapper (activates venv, runs headless) |
| `booking_config.json` | Recurring day/time window config |
| `.env` | Credentials (not committed) |
| `logs/` | Daily log files |
| `screenshots/` | Debug screenshots from each run |

## LaunchAgent

- Plist: `~/Library/LaunchAgents/com.alexdimitroff.bhawk-tee-time.plist`
- Runs headless — no display or unlocked screen required

### Useful Commands

```bash
# Check if loaded
launchctl list | grep bhawk

# Reload after plist changes
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.alexdimitroff.bhawk-tee-time.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alexdimitroff.bhawk-tee-time.plist

# Check wake schedule
pmset -g sched
```

## Manual Run

```bash
cd /Users/alexdimitroff/Space-City-Studios/bhawk-tee-time-booking
source venv/bin/activate
python book_tee_time.py                    # headless by default
HEADLESS=false python book_tee_time.py     # visible browser for debugging
DAYS_AHEAD=2 python book_tee_time.py       # override lead time
```

## Notes

- Uses `undetected-chromedriver` to bypass bot detection on the ezlinks booking system
- Auto-accepts "tee time adjustment" modal if the first slot gets taken
- Logs and screenshots auto-clean after 30 days
