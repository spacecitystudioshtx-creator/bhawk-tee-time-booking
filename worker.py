"""Scheduler / booking worker.

Runs in its own thread. Decides WHEN to act; the actual browser work is
submitted to the BrowserExecutor thread. Three jobs:

  1. SNIPE  — recurring config entries: warm up before 7:00 AM local, fire at
     7:00:00, retry for 20 minutes.
  2. POLL   — one-off target_dates: re-search every 3-7 minutes for cancellations.
  3. HEALTH — every 30 idle minutes, verify the session is still logged in and
     SMS if it isn't.

If a provider raises InterventionNeeded (CAPTCHA, login wall), the worker
pauses, texts the dashboard link, and waits for the user to hit Resume.
"""

import os
import time
import random
import logging
import threading
from datetime import datetime, date, timedelta

import notify
from status import Status, TZ, now_local, load_config, load_booked, mark_booked
from providers import get_provider
from providers.base import InterventionNeeded

log = logging.getLogger('bhawk').info

DRY_RUN = os.getenv('DRY_RUN', 'false').lower() == 'true'
DAYS_AHEAD = int(os.getenv('DAYS_AHEAD', '8'))
BOOKING_OPEN_HOUR = 7
SNIPE_WARMUP_MIN = 6
SNIPE_RETRY_WINDOW_MIN = 20
POLL_MIN_SECONDS = 3 * 60
POLL_MAX_SECONDS = 7 * 60
HEALTH_CHECK_SECONDS = 30 * 60

WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday',
            'saturday', 'sunday']


def next_snipe_event(config, booked):
    """Next (snipe_dt, target_date, t_start, t_end, provider) from recurring config."""
    default_provider = config.get('provider', 'blackhawk')
    best = None
    for entry in config.get('recurring', []):
        day = entry.get('day', '').lower()
        if day not in WEEKDAYS:
            continue
        for offset in range(0, 15):
            target = now_local().date() + timedelta(days=offset)
            if target.strftime('%A').lower() != day or str(target) in booked:
                continue
            snipe_dt = datetime.combine(
                target - timedelta(days=DAYS_AHEAD), datetime.min.time(),
                tzinfo=TZ).replace(hour=BOOKING_OPEN_HOUR)
            if snipe_dt + timedelta(minutes=SNIPE_RETRY_WINDOW_MIN) < now_local():
                continue
            ev = (snipe_dt, target,
                  float(entry.get('time_start', 9)),
                  float(entry.get('time_end', 12)),
                  entry.get('provider', default_provider))
            if best is None or ev[0] < best[0]:
                best = ev
    return best


def poll_targets(config, booked):
    default_provider = config.get('provider', 'blackhawk')
    out = []
    for entry in config.get('target_dates', []):
        try:
            d = date.fromisoformat(entry['date'])
        except (KeyError, ValueError):
            continue
        if d >= now_local().date() and str(d) not in booked:
            out.append((d, float(entry.get('time_start', 0)),
                        float(entry.get('time_end', 24)),
                        entry.get('provider', default_provider)))
    return out


class Worker(threading.Thread):
    def __init__(self, executor, status: Status):
        super().__init__(daemon=True, name='worker')
        self.executor = executor
        self.status = status
        self._last_health = 0.0

    # ----------------------------------------------------------- attempts
    def _attempt(self, provider_name, target, t_start, t_end):
        """One attempt on the browser thread. Returns result string."""
        provider = get_provider(provider_name)
        try:
            result = self.executor.submit(
                lambda m: provider.attempt(m, target, t_start, t_end, dry_run=DRY_RUN),
                timeout=15 * 60)
            self.status.set(last_result=f"{result} ({target}, {provider_name})",
                            browser_ok=True, login_ok=True)
            self.status.event(f"Attempt for {target}: {result}")
            return result
        except InterventionNeeded as e:
            self.status.pause(str(e))
            notify.sms(f"⚠️ Golf bot needs help: {e}. Take control from the dashboard, "
                       f"then hit Resume.", dedupe_key='intervention', with_link=True)
            return 'paused'
        except NotImplementedError as e:
            self.status.event(f"Provider '{provider_name}' not implemented: {e}")
            return 'error'
        except Exception as e:
            log(f"Attempt error: {e}")
            self.status.event(f"Attempt error: {e}")
            self.status.set(browser_ok=False, last_result=f"error ({target})")
            try:
                self.executor.submit(lambda m: m.restart(), timeout=120)
                self.status.set(browser_ok=True)
            except Exception as e2:
                log(f"Browser restart failed: {e2}")
            return 'error'

    def _booked(self, target, result_note=''):
        mark_booked(str(target))
        notify.sms(f"✅ Tee time booked for {target:%A %b %d}! {result_note}".strip())
        self.status.event(f"BOOKED {target}")

    def _wait_while_paused(self):
        while self.status.get('paused'):
            time.sleep(5)

    # ----------------------------------------------------------- snipe
    def _run_snipe(self, snipe_dt, target, t_start, t_end, provider_name):
        warmup_dt = snipe_dt - timedelta(minutes=SNIPE_WARMUP_MIN)
        if now_local() < warmup_dt:
            return False
        log(f"SNIPE MODE for {target} ({t_start}-{t_end}) via {provider_name}")
        self.status.event(f"Snipe mode: {target} at {snipe_dt:%H:%M}")

        # Warm the session so the 7:00 attempt skips login
        provider = get_provider(provider_name)
        try:
            self.executor.submit(lambda m: provider.ensure_logged_in(m), timeout=180)
            self.status.set(login_ok=True, browser_ok=True)
        except InterventionNeeded as e:
            self.status.pause(str(e))
            notify.sms(f"⚠️ Login problem before the {snipe_dt:%H:%M} booking window: {e}. "
                       f"Fix it before 7:00!", dedupe_key='intervention', with_link=True)
            self._wait_while_paused()
        except Exception as e:
            log(f"Warmup failed ({e}); will still try at open.")

        while now_local() < snipe_dt:
            time.sleep(min(1, max(0.05, (snipe_dt - now_local()).total_seconds())))

        deadline = snipe_dt + timedelta(minutes=SNIPE_RETRY_WINDOW_MIN)
        while now_local() < deadline:
            self._wait_while_paused()
            result = self._attempt(provider_name, target, t_start, t_end)
            if result == 'success':
                self._booked(target)
                return True
            wait = random.uniform(20, 45)
            log(f"Snipe attempt: {result}. Retrying in {wait:.0f}s...")
            time.sleep(wait)
        notify.sms(f"❌ No tee time found for {target:%A %b %d} "
                   f"in the {SNIPE_RETRY_WINDOW_MIN}-min window.")
        self.status.event(f"Snipe window closed without booking {target}")
        return False

    # ----------------------------------------------------------- health
    def _health_check(self):
        if time.time() - self._last_health < HEALTH_CHECK_SECONDS:
            return
        self._last_health = time.time()
        # Skip if a long browser job is queued/running
        if self.executor.busy():
            return
        try:
            ok = self.executor.submit(
                lambda m: get_provider('blackhawk').check_session(m), timeout=120)
            self.status.set(login_ok=ok, browser_ok=True,
                            last_health_check=now_local().isoformat())
            if ok:
                notify._last_sent.pop('login', None)  # re-arm the alert
            else:
                notify.sms("⚠️ Golf bot session expired — log back in from the "
                           "dashboard before the next booking window.",
                           dedupe_key='login', with_link=True)
            self.status.event(f"Health check: {'logged in' if ok else 'LOGGED OUT'}")
        except Exception as e:
            self.status.set(browser_ok=False)
            self.status.event(f"Health check failed: {e}")

    # ----------------------------------------------------------- main loop
    def run(self):
        notify.sms("Golf bot started." + (" (DRY RUN)" if DRY_RUN else ""),
                   dedupe_key='startup')
        while True:
            try:
                self._tick()
            except Exception as e:
                log(f"Worker loop error: {e}")
                self.status.event(f"Worker loop error: {e}")
                time.sleep(60)

    def _tick(self):
        self._wait_while_paused()
        config = load_config()
        booked = load_booked()
        snipe = next_snipe_event(config, booked)
        targets = poll_targets(config, booked)

        secs_to_warmup = None
        if snipe:
            snipe_dt, target, ts, te, prov = snipe
            self.status.set(next_action=f"Snipe {target} at {snipe_dt:%a %m/%d %H:%M} "
                                        f"(window {ts}-{te}, {prov})")
            if self._run_snipe(snipe_dt, target, ts, te, prov):
                return
            secs_to_warmup = (snipe_dt - timedelta(minutes=SNIPE_WARMUP_MIN)
                              - now_local()).total_seconds()
        elif not targets:
            self.status.set(next_action="Idle — nothing scheduled")

        if targets:
            d, ts, te, prov = targets[0]
            self.status.set(next_action=f"Polling {d} for cancellations "
                                        f"(window {ts}-{te}, {prov})")
            result = self._attempt(prov, d, ts, te)
            if result == 'success':
                self._booked(d, '(cancellation grabbed)')
                return
            sleep_secs = random.uniform(POLL_MIN_SECONDS, POLL_MAX_SECONDS)
        else:
            self._health_check()
            sleep_secs = 5 * 60

        if secs_to_warmup is not None and secs_to_warmup > 0:
            sleep_secs = max(30, min(sleep_secs, secs_to_warmup))
        time.sleep(sleep_secs)
