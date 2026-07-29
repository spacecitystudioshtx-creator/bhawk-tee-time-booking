"""Persistent browser management.

Playwright's sync API is bound to the thread that created it, so ALL browser
work runs on one dedicated BrowserExecutor thread. Other threads (scheduler,
web dashboard) call executor.submit(fn) and get the result back.

The browser itself is long-lived: one Chromium with a persistent profile so
login cookies survive between attempts and restarts.
"""

import os
import queue
import shutil
import logging
import threading
from datetime import datetime

from playwright.sync_api import sync_playwright

from status import SCREENSHOT_DIR, TZ, now_local

log = logging.getLogger('bhawk').info

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(SCRIPT_DIR, '.pw-bhcc-profile')
HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'
VIEWPORT = {'width': 1280, 'height': 800}


class BrowserManager:
    """Owns the persistent Chromium context. Only touch from the executor thread."""

    def __init__(self):
        self.pw = None
        self.context = None

    def start(self):
        if self.context:
            return
        log("Launching persistent Chromium...")
        self.pw = sync_playwright().start()
        exe = (os.getenv('CHROMIUM_PATH') or shutil.which('chromium')
               or shutil.which('chromium-browser'))
        kwargs = dict(
            user_data_dir=PROFILE_DIR,
            headless=HEADLESS,
            viewport=VIEWPORT,
            locale='en-US',
            timezone_id=str(TZ),
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ],
        )
        if exe:
            log(f"Using system browser: {exe}")
            kwargs['executable_path'] = exe
        self.context = self.pw.chromium.launch_persistent_context(**kwargs)
        # Headless builds advertise "HeadlessChrome" in the UA — a bot-detection
        # giveaway. Detect and relaunch once with a cleaned UA.
        if HEADLESS:
            probe = self.context.pages[0] if self.context.pages else self.context.new_page()
            ua = probe.evaluate('navigator.userAgent')
            if 'HeadlessChrome' in ua:
                self.context.close()
                kwargs['user_agent'] = ua.replace('HeadlessChrome', 'Chrome')
                log("Masked headless UA.")
                self.context = self.pw.chromium.launch_persistent_context(**kwargs)
        self.context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        self.context.set_default_timeout(30_000)

    def stop(self):
        for obj, closer in ((self.context, 'close'), (self.pw, 'stop')):
            try:
                if obj:
                    getattr(obj, closer)()
            except Exception:
                pass
        self.context = None
        self.pw = None

    def restart(self):
        log("Restarting browser...")
        self.stop()
        self.start()

    def page(self):
        """The single working page; closes stray tabs from previous attempts."""
        self.start()
        for extra in self.context.pages[1:]:
            try:
                extra.close()
            except Exception:
                pass
        return self.context.pages[0] if self.context.pages else self.context.new_page()

    def current_page(self):
        """Most recently opened page (e.g. the booking tab) without closing anything."""
        self.start()
        pages = self.context.pages
        return pages[-1] if pages else self.context.new_page()

    def screenshot_file(self, page, name):
        path = os.path.join(SCREENSHOT_DIR, f'{name}_{now_local():%Y-%m-%d_%H%M%S}.png')
        try:
            page.screenshot(path=path)
            log(f"Screenshot saved: {path}")
        except Exception as e:
            log(f"Screenshot failed: {e}")
        return path

    def screenshot_bytes(self):
        return self.current_page().screenshot()

    def click_at(self, x, y):
        self.current_page().mouse.click(x, y)

    def type_text(self, text):
        self.current_page().keyboard.type(text, delay=40)

    def press_key(self, key):
        self.current_page().keyboard.press(key)


class BrowserExecutor(threading.Thread):
    """Single thread that owns the browser; other threads submit callables."""

    def __init__(self):
        super().__init__(daemon=True, name='browser-executor')
        self.manager = BrowserManager()
        self.tasks = queue.Queue()

    def run(self):
        while True:
            fn, done, holder = self.tasks.get()
            try:
                holder['result'] = fn(self.manager)
            except Exception as e:
                holder['error'] = e
            finally:
                done.set()

    def submit(self, fn, timeout=None):
        """Run fn(manager) on the browser thread; blocks until done."""
        done = threading.Event()
        holder = {}
        self.tasks.put((fn, done, holder))
        if not done.wait(timeout):
            raise TimeoutError("Browser task timed out (a long job may be running).")
        if 'error' in holder:
            raise holder['error']
        return holder.get('result')

    def busy(self):
        return not self.tasks.empty()
