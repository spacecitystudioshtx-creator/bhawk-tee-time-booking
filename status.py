"""Thread-safe application state + event log + booked-date persistence."""

import os
import json
import threading
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.getenv('BOOKING_TZ', 'America/Chicago'))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, 'logs')
SCREENSHOT_DIR = os.path.join(SCRIPT_DIR, 'screenshots')
BOOKED_FILE = os.path.join(LOG_DIR, 'booked_dates.json')
CONFIG_FILE = os.path.join(SCRIPT_DIR, 'booking_config.json')

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def now_local():
    return datetime.now(TZ)


class Status:
    """Single shared object: live state for the dashboard + rolling event log."""

    def __init__(self):
        self._lock = threading.Lock()
        self.events = deque(maxlen=300)
        self.data = {
            'started_at': now_local().isoformat(),
            'browser_ok': False,
            'login_ok': None,          # None = unknown yet
            'last_health_check': None,
            'next_action': None,       # human-readable description
            'last_result': None,
            'paused': False,
            'pause_reason': None,
        }

    def set(self, **kw):
        with self._lock:
            self.data.update(kw)

    def get(self, key):
        with self._lock:
            return self.data.get(key)

    def event(self, msg):
        with self._lock:
            self.events.appendleft(f"[{now_local():%Y-%m-%d %H:%M:%S}] {msg}")

    def pause(self, reason):
        self.set(paused=True, pause_reason=reason)
        self.event(f"PAUSED: {reason}")

    def resume(self):
        self.set(paused=False, pause_reason=None)
        self.event("Resumed by user.")

    def snapshot(self):
        with self._lock:
            return {**self.data, 'events': list(self.events)}


def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {'recurring': [], 'target_dates': []}


def load_booked():
    try:
        with open(BOOKED_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def mark_booked(date_str):
    booked = load_booked()
    booked.add(date_str)
    with open(BOOKED_FILE, 'w') as f:
        json.dump(sorted(booked), f)
