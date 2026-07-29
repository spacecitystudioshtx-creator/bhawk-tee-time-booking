# Golf Tee Time Booking Service

A continuously-running booking service (V1: personal, single-user) hosted on
Replit. One persistent Chromium browser stays logged in 24/7; a scheduler
snipes tee times the moment they open and polls for cancellations; SMS alerts
keep you in the loop; and a phone-friendly dashboard lets you watch the live
browser and take control when a CAPTCHA or login wall needs a human.

## Architecture

```
server.py                 entrypoint: starts everything
├── browser.py            ONE persistent Playwright Chromium (cookies survive
│                         restarts via .pw-bhcc-profile/); all browser work
│                         runs on a single executor thread
├── worker.py             scheduler: 7:00 AM snipes, cancellation polling,
│                         30-min session health checks, pause/resume
├── providers/
│   ├── base.py           BookingProvider interface + InterventionNeeded
│   ├── blackhawk.py      Black Hawk CC (EZLinks) — fully implemented
│   └── memorial.py       Memorial Park Houston — scaffold (see file docstring)
├── web.py                FastAPI dashboard (status, logs, live view,
│                         click/type passthrough, pause/resume/restart)
├── notify.py             Twilio SMS (log-only until secrets are set)
└── status.py             shared state, config, booked-date tracking
```

## Replit setup

1. Create a blank **Python** Repl → upload the package zip → extract
   (`unzip *.zip` in the Shell if needed).
2. Shell: `pip install -r requirements.txt`
   ([replit.nix](replit.nix) provides system Chromium automatically).
3. **Secrets** (Tools → Secrets):

   | Secret | Required | Purpose |
   |---|---|---|
   | `BHCC_USERNAME` / `BHCC_PASSWORD` | yes | Black Hawk login |
   | `DASHBOARD_PASSWORD` | yes | dashboard auth (it fails closed without it) |
   | `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM` / `SMS_TO` | for SMS | Twilio credentials + your phone number |
   | `DASHBOARD_URL` | recommended | your deployed URL, appended to alert texts |
   | `DRY_RUN` | first test | `true` = stop right before the final Finish click |

4. Hit **Run** — open the webview, log in with any username + your
   `DASHBOARD_PASSWORD`.
5. When happy: **Deploy → Reserved VM → Web Server**. (Autoscale sleeps
   between requests and kills the browser; Reserved VM keeps it alive.)
   Put the deployment URL in the `DASHBOARD_URL` secret.

## booking_config.json

```json
{
  "provider": "blackhawk",
  "recurring": [
    { "day": "friday",   "time_start": 9.5, "time_end": 10.5 }
  ],
  "target_dates": [
    { "date": "2026-08-01", "time_start": 9.0, "time_end": 12.0 }
  ]
}
```

- **recurring** → snipe mode: 8 days before each matching date (`DAYS_AHEAD`),
  the worker warms up the session at ~6:54 AM Central, fires at 7:00:00, then
  retries every 20–45 s for 20 minutes. SMS on success or failure.
- **target_dates** → poll mode: re-searches every 3–7 minutes for
  cancellations. Times are decimal hours (9.5 = 9:30 AM).
- Per-entry `"provider"` overrides the top-level one (for Memorial Park later).
- Config is re-read every loop — edit it live, no restart needed.
- Booked dates land in `logs/booked_dates.json` and are never re-booked.

## Human-in-the-loop

When the provider hits a CAPTCHA or an unexpected login wall it raises
`InterventionNeeded`: the worker pauses, texts you the dashboard link, and
leaves the browser exactly where it is. On the dashboard, **Take Control**
shows a live screenshot — tap to click, type into the text box — solve the
challenge yourself, then hit **Resume**. Nothing restarts; the same browser
session continues.

## Bot-detection design

- One long-lived browser + persistent profile → login cookies stay warm,
  logins are rare (the #1 flag is a fresh login every run).
- Headless User-Agent masked, `navigator.webdriver` hidden, automation blink
  feature disabled.
- Randomized retry/poll intervals.
- **Caveat:** Replit egress uses datacenter IPs. If EZLinks blocks by IP
  reputation, browser stealth can't fix that — the fallback is running this
  same service on a home machine (it's plain Python, nothing Replit-specific).

## Memorial Park (V2 first step)

[providers/memorial.py](providers/memorial.py) is a scaffold. To implement it,
walk the real Memorial Park booking flow once with devtools open, record the
login/search/reserve selectors, and fill in the three methods following
[providers/blackhawk.py](providers/blackhawk.py) as the template. Everything
else (scheduler, dashboard, SMS, browser) already works for any provider.

## Legacy

`book_tee_time.py` is the old single-run Selenium/launchd version for the Mac.
It still works but is superseded by this service.
