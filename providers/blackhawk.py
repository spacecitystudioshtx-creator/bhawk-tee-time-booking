"""Black Hawk Country Club (EZLinks) booking provider.

Selectors and Angular-scope tricks ported from the proven Selenium flow.
"""

import os
import logging
from datetime import datetime

from playwright.sync_api import TimeoutError as PWTimeout

from providers.base import BookingProvider, InterventionNeeded

log = logging.getLogger('bhawk').info

LOGIN_URL = 'https://www.bhawkcc.com/about-black-hawk-country-club/login?E=3'
BOOKING_LINK_HREF = '/club/scripts/interfaces/ezlinks.asp'
PLAYER_COUNTS = [4, 3, 2, 1]


class BlackHawkProvider(BookingProvider):
    name = 'blackhawk'

    # ------------------------------------------------------------- session
    def _login_form(self, page):
        return page.locator('input#login_username_main[name="user"]')

    def check_session(self, manager):
        page = manager.page()
        page.goto(LOGIN_URL, wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        form = self._login_form(page)
        return form.count() == 0 or not form.first.is_visible()

    def _detect_captcha(self, page):
        try:
            if (page.locator('iframe[src*="recaptcha"], iframe[src*="hcaptcha"]').count() > 0
                    or page.locator('[class*="captcha" i]').count() > 0):
                return True
        except Exception:
            pass
        return False

    def ensure_logged_in(self, manager):
        page = manager.page()
        page.goto(LOGIN_URL, wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        form = self._login_form(page)
        if form.count() == 0 or not form.first.is_visible():
            log("Session still valid — skipping login.")
            return
        if self._detect_captcha(page):
            manager.screenshot_file(page, 'captcha_login')
            raise InterventionNeeded("CAPTCHA on Black Hawk login page")
        username = os.getenv('BHCC_USERNAME')
        password = os.getenv('BHCC_PASSWORD')
        if not username or not password:
            raise RuntimeError("BHCC_USERNAME / BHCC_PASSWORD secrets not set")
        log("Logging in to Black Hawk...")
        form.first.fill(username)
        page.fill('input#login_password_main[name="pw"]', password)
        page.wait_for_timeout(1000)
        page.click('button#login_submit_main[name="MemEnter"]')
        page.wait_for_timeout(4000)
        # Still on the login form? Bad credentials or a challenge — human needed.
        form = self._login_form(page)
        if form.count() > 0 and form.first.is_visible():
            manager.screenshot_file(page, 'login_failed')
            raise InterventionNeeded("Black Hawk login did not go through")
        manager.screenshot_file(page, 'after_login')

    # ------------------------------------------------------------- helpers
    def _open_tee_sheet(self, manager, page):
        log("Opening Book A Tee Time...")
        page.click('div.nav-trigger')
        page.wait_for_timeout(2000)
        link = page.locator(f'a[href="{BOOKING_LINK_HREF}"]')
        if link.count() == 0:
            link = page.locator('a', has_text='Book A Tee Time')
        tee = page
        try:
            with manager.context.expect_page(timeout=8000) as popup:
                link.first.click()
            tee = popup.value
        except PWTimeout:
            pass  # loaded in the same tab
        tee.wait_for_load_state('domcontentloaded')
        # Let the Angular app fully initialize before touching anything —
        # rushing this page is what causes the endless "Please wait" spinner.
        tee.wait_for_timeout(5000)
        tee.wait_for_selector('input#dateInput', state='visible', timeout=30_000)
        tee.wait_for_timeout(2000)
        return tee

    def _type_date(self, tee, date_str, day_number):
        """Enter the date with real keystrokes, paced like a human.
        The EZLinks datepicker ignores programmatically-set values (fill),
        which leaves Angular's model empty and the search stuck on
        'Please wait'. Keystrokes + the calendar-day click are required."""
        date_input = tee.locator('input#dateInput')
        date_input.click()
        tee.wait_for_timeout(1000)
        date_input.press('Control+a')
        date_input.press('Delete')
        tee.wait_for_timeout(300)
        date_input.press_sequentially(date_str, delay=120)
        tee.wait_for_timeout(1000)
        tee.keyboard.press('Enter')
        tee.wait_for_timeout(2000)
        for day_link in tee.locator('a.ui-state-default').all():
            if day_link.inner_text().strip() == day_number:
                day_link.click()
                break
        tee.wait_for_timeout(2000)

    def _set_date(self, tee, target_date):
        date_str = f'{target_date:%m/%d/%Y}'
        log(f"Selecting date: {date_str}")
        self._type_date(tee, date_str, str(target_date.day))
        # Verify it registered; retype once if the field disagrees.
        try:
            val = tee.locator('input#dateInput').input_value().strip()
            if val != date_str:
                log(f"Date field shows '{val}', expected '{date_str}' — retyping...")
                self._type_date(tee, date_str, str(target_date.day))
        except Exception:
            pass

    def _wait_not_busy(self, tee, timeout=30_000):
        """Returns True once the cg-busy 'Please wait' overlay is gone."""
        try:
            tee.wait_for_selector('div.cg-busy-animation', state='hidden', timeout=timeout)
            tee.wait_for_timeout(1000)
            return True
        except PWTimeout:
            log("Warning: cg-busy overlay still present.")
            tee.wait_for_timeout(1000)
            return False

    def _check_all_filters(self, tee):
        result = tee.evaluate("""() => {
            try {
                var allCbs = document.querySelectorAll('input[type="checkbox"]');
                var count = 0;
                for (var cb of allCbs) {
                    cb.checked = true;
                    cb.dispatchEvent(new Event('change', {bubbles: true}));
                    count++;
                }
                try {
                    var sc = angular.element(document.body).scope();
                    if (sc && sc.$apply) sc.$apply();
                } catch(e2) {}
                return 'set ' + count + ' checkboxes';
            } catch(e) { return 'error: ' + e.message; }
        }""")
        log(f"Filter checkboxes: {result}")
        self._wait_not_busy(tee, timeout=20_000)

    def _set_players(self, tee, num_players):
        span = tee.locator('span[data-ng-bind="ec.playersFilterDataBinding()"]')
        try:
            span.first.wait_for(state='attached', timeout=10_000)
        except PWTimeout:
            log("Players span not found — skipping player filter")
            return False
        if span.first.inner_text().strip() == str(num_players):
            return True
        result = span.first.evaluate("""(el, numPlayers) => {
            try {
                var scope;
                for (var i = 0; i < 15; i++) {
                    scope = angular.element(el).scope();
                    if (scope && scope.ec) break;
                    el = el.parentElement;
                    if (!el) break;
                }
                if (!scope || !scope.ec) return 'ec not found';
                var fs = scope.ec.filterSettings;
                var playerKey = null;
                for (var k of Object.keys(fs||{})) {
                    if (k.toLowerCase().includes('player')) { playerKey = k; break; }
                }
                if (!playerKey) return 'no player key in: ' + Object.keys(fs||{}).join(',');
                var old = fs[playerKey];
                fs[playerKey] = numPlayers;
                scope.$apply();
                var triggered = '';
                for (var m of ['search','doSearch','getResults','onPlayersChange',
                               'onFilterChange','filterChanged','performSearch']) {
                    if (typeof scope.ec[m] === 'function') {
                        scope.ec[m](); triggered = m; break;
                    }
                }
                return 'set ' + playerKey + ' ' + old + '->' + numPlayers +
                       ' triggered:' + (triggered||'none');
            } catch(e) { return 'error: ' + e.message; }
        }""", num_players)
        log(f"Players scope result: {result}")
        self._wait_not_busy(tee, timeout=20_000)
        return bool(result) and result.startswith('set ')

    def _accept_adjustment(self, tee, timeout=1500):
        try:
            tee.locator(
                "xpath=//div[contains(@class,'modal') and contains(@class,'in')]"
                "//button[contains(., 'Yes')]").first.click(timeout=timeout)
            log("Accepted alternative tee time (adjustment modal).")
            return True
        except Exception:
            return False

    def _click_any(self, tee, selectors, timeout=10_000):
        for sel in selectors:
            try:
                tee.locator(sel).first.click(timeout=timeout)
                return True
            except Exception:
                continue
        return False

    # ------------------------------------------------------------- attempt
    def attempt(self, manager, target_date, t_start, t_end, dry_run=False):
        page = manager.page()
        self.ensure_logged_in(manager)
        tee = self._open_tee_sheet(manager, page)
        self._set_date(tee, target_date)
        tee.click("button:has-text('Search')")
        log(f"Clicked Search at {datetime.now():%H:%M:%S.%f}")
        if not self._wait_not_busy(tee, timeout=45_000):
            # Overlay never cleared — the classic stuck "Please wait" state.
            # Bail out; the worker retries with a fresh page next cycle.
            manager.screenshot_file(tee, 'stuck_please_wait')
            log("Search stuck on 'Please wait' — aborting this attempt.")
            return 'error'
        self._check_all_filters(tee)

        candidates, players_used = [], None
        for n in PLAYER_COUNTS:
            if not self._set_players(tee, n):
                continue
            try:
                tee.wait_for_selector('span.time.ng-binding', timeout=15_000)
            except PWTimeout:
                pass
            times = [t.inner_text().strip()
                     for t in tee.locator('span.time.ng-binding').all()]
            log(f"{len(times)} slot(s) with {n} players: {times}")
            for i, txt in enumerate(times):
                try:
                    t = datetime.strptime(txt, '%I:%M %p')
                    hour_dec = t.hour + t.minute / 60.0
                    if t_start <= hour_dec < t_end:
                        candidates.append((hour_dec, i, txt))
                except ValueError:
                    pass
            if candidates:
                players_used = n
                break

        if not candidates:
            log("No tee times in window for any player count.")
            manager.screenshot_file(tee, 'no_times')
            return 'no_times'

        candidates.sort(key=lambda c: c[0])  # earliest inside the window
        hour_dec, idx, txt = candidates[0]
        view_buttons = tee.locator(
            "xpath=//button[contains(@class,'primary-btn') and contains(text(),'View')]")
        if idx >= view_buttons.count():
            log("View button index out of range — page changed under us.")
            return 'error'
        log(f"Selecting {txt} ({players_used} players)")
        view_buttons.nth(idx).click()
        tee.wait_for_timeout(3000)

        self._accept_adjustment(tee, timeout=1000)
        cart_selectors = ['button#addToCartBtn',
                          "xpath=//button[contains(., 'Continue') and not(@disabled)]"]
        clicked = self._click_any(tee, cart_selectors)
        if not clicked and self._accept_adjustment(tee, timeout=2000):
            clicked = self._click_any(tee, cart_selectors)
        if not clicked:
            manager.screenshot_file(tee, 'cart_continue_not_found')
            return 'error'
        tee.wait_for_timeout(3000)
        self._accept_adjustment(tee, timeout=1000)

        log("Proceeding through payment page...")
        if not self._click_any(tee, [
            'button#buyTeeTime.tokenex_submit',
            'button#buyTeeTime',
            "xpath=//button[contains(., 'Continue') and not(@disabled)]",
            "xpath=//a[contains(., 'Continue')]",
        ], timeout=25_000):
            manager.screenshot_file(tee, 'payment_continue_not_found')
            return 'error'
        tee.wait_for_timeout(3000)

        if dry_run:
            log("DRY RUN — stopping before Finish. Flow works end to end.")
            manager.screenshot_file(tee, 'dry_run_final_page')
            return 'success'

        log("Finalizing reservation...")
        if not self._click_any(tee, [
            'button#topFinishBtn',
            "xpath=//button[contains(., 'Finish') and not(@disabled)]",
            "xpath=//button[contains(., 'Complete') and not(@disabled)]",
            "xpath=//button[contains(., 'Reserve') and not(@disabled)]",
        ], timeout=25_000):
            manager.screenshot_file(tee, 'finish_button_not_found')
            return 'error'
        tee.wait_for_timeout(5000)

        content = tee.content().lower()
        if any(s in content for s in ('reservation complete', 'confirmation', 'thank you')):
            log(f"SUCCESS! Booked {txt} on {target_date:%Y-%m-%d} "
                f"for {players_used} players.")
            manager.screenshot_file(tee, 'reservation_confirmation')
            return 'success'
        log("WARNING: reservation may not have completed — check manually.")
        manager.screenshot_file(tee, 'final_page')
        return 'error'
