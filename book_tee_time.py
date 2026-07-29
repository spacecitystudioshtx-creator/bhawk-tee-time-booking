#!/usr/bin/env python3
"""
Black Hawk Country Club Tee Time Booking Automation — Continuous Polling Mode
Polls every ~5 minutes (randomized) for cancellations on a specific date.
Books the first available tee time before 12 PM for 4 players.
Keeps running until a booking succeeds or the target date passes.
Uses undetected-chromedriver to bypass bot detection.
"""

import os
import sys
import time
import logging
import subprocess
import re
import random
from datetime import datetime, date
from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
from selenium.webdriver.support.ui import Select

# Resolve paths relative to this script's location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, 'logs')
SCREENSHOT_DIR = os.path.join(SCRIPT_DIR, 'screenshots')

# Create directories if they don't exist
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# Load environment variables
load_dotenv(os.path.join(SCRIPT_DIR, '.env'))

# Configuration
USERNAME = os.getenv('BHCC_USERNAME')
PASSWORD = os.getenv('BHCC_PASSWORD')
NUM_PLAYERS = 4

# TEST BOOKING: April 8 (Wednesday), any course, closest to noon, 3 players
TARGET_DATE = date(2026, 4, 8)
TARGET_TIME_START = 0.0    # any time
TARGET_TIME_END = 24.0

# Set to '' to skip course filtering (book any available course)
ALLOWED_COURSE_LABEL = ''

# Player counts to try in order (try all sizes to find any available slot)
PLAYER_COUNTS = [4, 3, 2, 1]

# Set to True to test the full flow without completing the final booking
DRY_RUN = False

# Pick the time closest to noon
PICK_CLOSEST_TO_NOON = True

# Polling interval: randomized between these bounds (seconds)
POLL_MIN_SECONDS = 3 * 60   # 3 minutes
POLL_MAX_SECONDS = 7 * 60   # 7 minutes

# Set to True when running on server (headless mode)
HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'


def setup_logging():
    """Configure logging to both console and a dated log file"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    log_file = os.path.join(LOG_DIR, f'booking_{today_str}.log')

    logger = logging.getLogger('bhawk_booking')
    logger.setLevel(logging.INFO)

    # Avoid adding duplicate handlers on re-import
    if not logger.handlers:
        formatter = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

        # Console handler
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        logger.addHandler(console)

        # File handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

_logger = setup_logging()

def log(message):
    """Print timestamped log message to console and log file"""
    _logger.info(message)


def save_screenshot(driver, name):
    """Save a screenshot with timestamp to the screenshots directory"""
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    filename = f'{name}_{timestamp}.png'
    filepath = os.path.join(SCREENSHOT_DIR, filename)
    driver.save_screenshot(filepath)
    log(f"Screenshot saved: {filepath}")
    return filepath

def wait_and_click(driver, by, value, timeout=30):
    """Wait for element and click it, with interception fallback."""
    last_error = None
    for _ in range(3):
        element = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )
        try:
            element.click()
            return element
        except ElementClickInterceptedException as e:
            last_error = e
            # Overlay race: JS click fallback is often enough to recover.
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
                driver.execute_script("arguments[0].click();", element)
                return element
            except Exception:
                time.sleep(0.15)
                continue
    if last_error:
        raise last_error
    raise TimeoutException(f"Could not click element: {by}={value}")

def wait_for_element(driver, by, value, timeout=30):
    """Wait for element to be present"""
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, value))
    )

def detect_chrome_version():
    """Detect installed Chrome major version to avoid ChromeDriver mismatch."""
    chrome_paths = [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        'google-chrome',
        'chromium-browser',
        'chromium',
    ]
    for path in chrome_paths:
        try:
            output = subprocess.check_output([path, '--version'], stderr=subprocess.DEVNULL, timeout=5)
            match = re.search(r'(\d+)\.', output.decode())
            if match:
                version = int(match.group(1))
                log(f"Detected Chrome version: {version}")
                return version
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            continue
    log("Could not detect Chrome version, letting undetected-chromedriver guess")
    return None

def click_any(driver, selectors, timeout=20):
    """Try multiple selectors and click the first available button."""
    for by, value in selectors:
        try:
            wait_and_click(driver, by, value, timeout=timeout)
            return True
        except TimeoutException:
            continue
        except ElementClickInterceptedException:
            continue
    return False

def accept_adjustment_if_present(driver, timeout=2):
    """Click Yes immediately if the tee-time-adjustment modal is shown."""
    try:
        yes_btn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//div[contains(@class,'modal') and contains(@class,'in')]//button[contains(., 'Yes')]"
            ))
        )
        try:
            yes_btn.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", yes_btn)
        log("Accepted alternative tee time (clicked Yes on adjustment modal).")
        return True
    except TimeoutException:
        return False

def attempt_booking():
    """
    Single booking attempt. Returns:
      'success'       — tee time booked
      'no_times'      — no times available in window (keep polling)
      'error'         — something went wrong (keep polling)
    """
    target_date = datetime(TARGET_DATE.year, TARGET_DATE.month, TARGET_DATE.day)
    log(f"Attempting to book: {target_date.strftime('%A, %B %d, %Y')}")
    log(f"Time window: {TARGET_TIME_START:.0f}:00-{TARGET_TIME_END:.0f}:00, course: {ALLOWED_COURSE_LABEL}, players: {PLAYER_COUNTS}")

    # Configure undetected Chrome
    log("Launching browser with undetected-chromedriver...")
    options = uc.ChromeOptions()
    options.add_argument('--window-size=1280,800')

    # Disable password save popup and other interruptions
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "profile.default_content_setting_values.notifications": 2,
    }
    options.add_experimental_option("prefs", prefs)

    # Headless mode — works when laptop is locked or lid is closed
    if HEADLESS:
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-position=0,0')
        options.add_argument('--disable-software-rasterizer')
        log("Running in headless mode (no display required)...")

    # Use a persistent profile to maintain cookies
    user_data_dir = os.path.expanduser('~/.uc-bhcc-profile')
    options.add_argument(f'--user-data-dir={user_data_dir}')

    chrome_version = detect_chrome_version()
    chrome_kwargs = dict(options=options, use_subprocess=True)
    if chrome_version:
        chrome_kwargs['version_main'] = chrome_version
    driver = uc.Chrome(**chrome_kwargs)

    try:
        # Step 1: Navigate to login page
        log("Navigating to login page...")
        driver.get('https://www.bhawkcc.com/about-black-hawk-country-club/login?E=3')
        time.sleep(3)

        # Step 2: Enter credentials and login
        log("Entering login credentials...")
        username_field = wait_for_element(driver, By.CSS_SELECTOR, 'input#login_username_main[name="user"]')
        username_field.clear()
        username_field.send_keys(USERNAME)

        password_field = wait_for_element(driver, By.CSS_SELECTOR, 'input#login_password_main[name="pw"]')
        password_field.clear()
        password_field.send_keys(PASSWORD)
        time.sleep(1)

        log("Submitting login...")
        wait_and_click(driver, By.CSS_SELECTOR, 'button#login_submit_main[name="MemEnter"]')
        time.sleep(4)
        save_screenshot(driver, 'after_login')

        # Step 3: Open menu
        log("Opening navigation menu...")
        wait_and_click(driver, By.CSS_SELECTOR, 'div.nav-trigger')
        time.sleep(2)

        # Step 4: Click "Book A Tee Time" link
        log("Clicking Book A Tee Time link...")

        # Store original window handle
        original_window = driver.current_window_handle

        # Wait for menu to fully open and find the link
        time.sleep(2)

        # Try multiple selectors for the booking link
        try:
            wait_and_click(driver, By.CSS_SELECTOR, 'a[href="/club/scripts/interfaces/ezlinks.asp"]', timeout=10)
        except TimeoutException:
            log("First selector failed, trying XPath with text...")
            try:
                wait_and_click(driver, By.XPATH, "//a[contains(text(), 'Book A Tee Time')]", timeout=10)
            except TimeoutException:
                log("XPath failed, trying partial link text...")
                wait_and_click(driver, By.PARTIAL_LINK_TEXT, "Book A Tee Time", timeout=10)

        time.sleep(3)

        # Switch to new tab if opened
        if len(driver.window_handles) > 1:
            for handle in driver.window_handles:
                if handle != original_window:
                    driver.switch_to.window(handle)
                    log("Switched to booking page tab...")
                    break

        # Wait for booking page to load
        log("Waiting for booking page to fully initialize...")
        time.sleep(5)

        # Wait for date input to be enabled
        try:
            WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'input#dateInput'))
            )
            log("Date input is ready!")
        except TimeoutException:
            log("Warning: Date input may still be loading, attempting to continue...")

        time.sleep(2)
        log("Successfully opened booking page...")

        # Step 5: Fill in date
        log(f"Selecting date: {target_date.strftime('%m/%d/%Y')}")
        date_input = wait_for_element(driver, By.CSS_SELECTOR, 'input#dateInput')
        date_input.click()
        time.sleep(1)

        # Clear and type the date
        date_input.clear()
        date_input.send_keys(target_date.strftime('%m/%d/%Y'))
        time.sleep(1)

        # Press Enter to confirm
        log("Pressing Enter to load calendar...")
        date_input.send_keys(Keys.ENTER)
        time.sleep(2)

        # Click the day in the calendar
        day_number = str(target_date.day)
        log(f"Clicking day {day_number} in calendar popup...")

        # Find and click the day link
        day_links = driver.find_elements(By.CSS_SELECTOR, 'a.ui-state-default')
        for link in day_links:
            if link.text.strip() == day_number:
                link.click()
                break
        time.sleep(2)

        # Step 6: Click Search to get to the results page
        log("Form is ready. Clicking search...")
        search_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Search')]"))
        )
        search_button.click()
        log("Clicked search button at " + datetime.now().strftime('%H:%M:%S.%f'))
        time.sleep(5)
        log(f"Current URL after search: {driver.current_url}")
        save_screenshot(driver, 'after_search_click')

        # Wait for the cg-busy loading overlay to disappear before touching filters
        log("Waiting for page to finish loading (cg-busy overlay)...")
        try:
            WebDriverWait(driver, 30).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, 'div.cg-busy-animation'))
            )
            log("Page loaded, overlay gone.")
        except TimeoutException:
            log("Warning: cg-busy overlay may still be present, attempting to proceed...")
        time.sleep(1)

        # Step 7a: Apply city + course filters once (before the player-count loop).
        # On page load ALL checkboxes start unchecked. We force-set them via .checked
        # + a dispatched 'change' event so Angular's ng-model picks up the change.
        if ALLOWED_COURSE_LABEL:
            # Specific course: check only that course; leave cities as-is (all unchecked
            # initially means EZLinks will scope to that course's city automatically).
            log(f"Selecting course: {ALLOWED_COURSE_LABEL} (and all cities)...")
            try:
                result = driver.execute_script(f"""
                    try {{
                        // Check all city checkboxes first
                        var allCbs = document.querySelectorAll('input[type="checkbox"]');
                        var cityCbs = [];
                        var courseCbs = [];
                        // Separate city vs course checkboxes by their label text
                        for (var cb of allCbs) {{
                            var lbl = cb.closest('label') || document.querySelector('label[for="' + cb.id + '"]');
                            var txt = lbl ? lbl.textContent.trim() : '';
                            var cities = ['Cypress','Humble','Richmond'];
                            var isCityLabel = cities.some(c => txt.includes(c));
                            if (isCityLabel) cityCbs.push(cb);
                            else if (txt.length > 0) courseCbs.push(cb);
                        }}
                        // Check all city checkboxes
                        for (var cb of cityCbs) {{
                            cb.checked = true;
                            cb.dispatchEvent(new Event('change', {{bubbles: true}}));
                        }}
                        // Check only the target course
                        var labels = document.querySelectorAll('label');
                        var targetCb = null;
                        for (var l of labels) {{
                            if (l.textContent.trim().includes('{ALLOWED_COURSE_LABEL}')) {{
                                targetCb = l.querySelector('input[type=checkbox]');
                                if (!targetCb) {{
                                    var fid = l.getAttribute('for');
                                    targetCb = fid ? document.getElementById(fid) : null;
                                }}
                                break;
                            }}
                        }}
                        if (!targetCb) return 'course label not found';
                        targetCb.checked = true;
                        targetCb.dispatchEvent(new Event('change', {{bubbles: true}}));
                        // Trigger Angular digest
                        try {{
                            var sc = angular.element(targetCb).scope();
                            if (sc) sc.$apply();
                        }} catch(e2) {{}}
                        return 'set ' + cityCbs.length + ' cities + 1 course';
                    }} catch(e) {{ return 'error: ' + e.message; }}
                """)
                log(f"Course filter result: {result}")
                time.sleep(3)
                try:
                    WebDriverWait(driver, 20).until(
                        EC.invisibility_of_element_located((By.CSS_SELECTOR, 'div.cg-busy-animation'))
                    )
                except TimeoutException:
                    pass
            except Exception as e2:
                log(f"Warning: could not select course checkbox: {e2}")
        else:
            # No course filter — check ALL city AND course checkboxes.
            log("No course filter — checking all city + course checkboxes...")
            try:
                result = driver.execute_script("""
                    try {
                        var allCbs = document.querySelectorAll('input[type="checkbox"]');
                        var count = 0;
                        for (var cb of allCbs) {
                            cb.checked = true;
                            cb.dispatchEvent(new Event('change', {bubbles: true}));
                            count++;
                        }
                        // Trigger Angular digest once after all changes
                        try {
                            var sc = angular.element(document.body).scope();
                            if (sc && sc.$apply) sc.$apply();
                        } catch(e2) {}
                        return 'set ' + count + ' checkboxes';
                    } catch(e) { return 'error: ' + e.message; }
                """)
                log(f"All checkboxes result: {result}")
                time.sleep(2)
                try:
                    WebDriverWait(driver, 20).until(
                        EC.invisibility_of_element_located((By.CSS_SELECTOR, 'div.cg-busy-animation'))
                    )
                except TimeoutException:
                    pass
            except Exception as e:
                log(f"Warning: could not check all checkboxes: {e}")

        # Step 7b–7d: Try each player count in order; stop at the first count with results
        candidates = []
        num_players_used = None
        for num_players in PLAYER_COUNTS:
            log(f"Setting players filter to {num_players}...")
            players_set = False
            try:
                player_span = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR,
                        'span[data-ng-bind="ec.playersFilterDataBinding()"]'))
                )
                current_players = player_span.text.strip()
                log(f"Found players span, current text: '{current_players}'")

                if current_players == str(num_players):
                    log(f"Players already set to {num_players}, no scope change needed")
                    players_set = True
                else:
                    result = driver.execute_script(f"""
                        try {{
                            var el = arguments[0];
                            var scope;
                            for (var i = 0; i < 15; i++) {{
                                scope = angular.element(el).scope();
                                if (scope && scope.ec) break;
                                el = el.parentElement;
                                if (!el) break;
                            }}
                            if (!scope || !scope.ec) return 'ec not found';
                            var fs = scope.ec.filterSettings;
                            var playerKey = null;
                            for (var k of Object.keys(fs||{{}})) {{
                                if (k.toLowerCase().includes('player')) {{ playerKey = k; break; }}
                            }}
                            if (!playerKey) return 'no player key in: ' + Object.keys(fs||{{}}).join(',');
                            var old = fs[playerKey];
                            fs[playerKey] = {num_players};
                            scope.$apply();
                            var triggered = '';
                            for (var m of ['search','doSearch','getResults','onPlayersChange',
                                           'onFilterChange','filterChanged','performSearch']) {{
                                if (typeof scope.ec[m] === 'function') {{
                                    scope.ec[m](); triggered = m; break;
                                }}
                            }}
                            return 'set ' + playerKey + ' ' + old + '->' + {num_players} + ' triggered:' + (triggered||'none');
                        }} catch(e) {{ return 'error: ' + e.message; }}
                    """, player_span)
                    log(f"Angular scope result: {result}")
                    players_set = result and result.startswith('set ')

                # Wait for the search to re-run after player change
                time.sleep(2)
                try:
                    WebDriverWait(driver, 20).until(
                        EC.invisibility_of_element_located((By.CSS_SELECTOR, 'div.cg-busy-animation'))
                    )
                    log("Search complete after player filter change")
                except TimeoutException:
                    log("Warning: cg-busy still showing after player change")
                time.sleep(1)

            except Exception as e:
                log(f"Could not set players via Angular scope: {e}")

            if not players_set:
                log(f"Warning: could not set players filter to {num_players} — skipping")
                continue

            # Check for results with this player count
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'span.time.ng-binding'))
                )
                log(f"Tee times found with {num_players} players!")
            except TimeoutException:
                pass  # may be 0 results — that's fine, we'll check below

            time_spans = driver.find_elements(By.CSS_SELECTOR, 'span.time.ng-binding')
            log(f"Found {len(time_spans)} time slot(s) with {num_players} players")

            if len(time_spans) > 0:
                num_players_used = num_players
                view_buttons = driver.find_elements(By.XPATH, "//button[contains(@class, 'primary-btn') and contains(text(), 'View')]")
                for i, time_span in enumerate(time_spans):
                    try:
                        time_text = time_span.text.strip()
                        time_obj = datetime.strptime(time_text, '%I:%M %p')
                        hour_decimal = time_obj.hour + time_obj.minute / 60.0
                        if PICK_CLOSEST_TO_NOON:
                            candidates.append((hour_decimal, i, time_text))
                        elif TARGET_TIME_START <= hour_decimal < TARGET_TIME_END:
                            candidates.append((hour_decimal, i, time_text))
                    except Exception as e:
                        log(f"Error parsing time at index {i}: {e}")
                if candidates:
                    break  # found viable slots; stop trying more player counts
                else:
                    log(f"Slots exist with {num_players} players but none in target window — trying next count")

        save_screenshot(driver, 'after_filters')

        if PICK_CLOSEST_TO_NOON and candidates:
            candidates.sort(key=lambda x: abs(x[0] - 12.0))
            log(f"All available times (players={num_players_used}): {[c[2] for c in candidates]}")

        found_time = False
        for hour_decimal, i, time_text in candidates:
            view_buttons = driver.find_elements(By.XPATH, "//button[contains(@class, 'primary-btn') and contains(text(), 'View')]")
            if i < len(view_buttons):
                log(f"Selecting: {time_text} ({num_players_used} players, index {i})")
                view_buttons[i].click()
                found_time = True
                time.sleep(3)
                break

        if not found_time:
            log("No available tee times found for any player count. Will retry...")
            save_screenshot(driver, 'no_times_available')
            return 'no_times'

        # Step 8: Handle popup - click Continue
        # If the first slot was taken, accept replacement immediately.
        accept_adjustment_if_present(driver, timeout=1)
        log("Confirming reservation details in popup...")
        time.sleep(2)
        clicked_add_to_cart = click_any(driver, [
            (By.CSS_SELECTOR, 'button#addToCartBtn'),
            (By.XPATH, "//button[contains(., 'Continue') and not(@disabled)]"),
        ], timeout=10)
        if not clicked_add_to_cart:
            # One more fast adjustment check, then retry once.
            if accept_adjustment_if_present(driver, timeout=2):
                clicked_add_to_cart = click_any(driver, [
                    (By.CSS_SELECTOR, 'button#addToCartBtn'),
                    (By.XPATH, "//button[contains(., 'Continue') and not(@disabled)]"),
                ], timeout=8)
        if not clicked_add_to_cart:
            save_screenshot(driver, 'cart_continue_not_found')
            log("ERROR: Could not find cart continue button.")
            return 'error'
        time.sleep(3)

        # Step 8b: Handle "Tee Time Adjustment" popup if it appears
        # This happens when someone else grabbed the time before us
        if not accept_adjustment_if_present(driver, timeout=1):
            log("No adjustment needed, proceeding...")

        # Step 9: Click Continue on payment page
        log("Proceeding through payment page...")
        clicked_continue = click_any(driver, [
            (By.CSS_SELECTOR, 'button#buyTeeTime.tokenex_submit'),
            (By.CSS_SELECTOR, 'button#buyTeeTime'),
            (By.XPATH, "//button[contains(., 'Continue') and not(@disabled)]"),
            (By.XPATH, "//a[contains(., 'Continue')]"),
        ], timeout=25)
        if not clicked_continue:
            save_screenshot(driver, 'payment_continue_not_found')
            log("ERROR: Could not find payment continue button.")
            return 'error'
        time.sleep(3)

        # Step 10: Click Finish Reservation
        if DRY_RUN:
            log("DRY RUN — stopping before final booking button. All steps up to here succeeded!")
            save_screenshot(driver, 'dry_run_final_page')
            return 'success'

        log("Finalizing reservation...")
        clicked_finish = click_any(driver, [
            (By.CSS_SELECTOR, 'button#topFinishBtn'),
            (By.XPATH, "//button[contains(., 'Finish') and not(@disabled)]"),
            (By.XPATH, "//button[contains(., 'Complete') and not(@disabled)]"),
            (By.XPATH, "//button[contains(., 'Reserve') and not(@disabled)]"),
        ], timeout=25)
        if not clicked_finish:
            save_screenshot(driver, 'finish_button_not_found')
            log("ERROR: Could not find final reservation button.")
            return 'error'
        time.sleep(3)

        # Step 11: Verify success
        time.sleep(2)
        page_content = driver.page_source.lower()

        if 'reservation complete' in page_content or 'confirmation' in page_content or 'thank you' in page_content:
            log("SUCCESS! Tee time reservation completed!")
            save_screenshot(driver, 'reservation_confirmation')
            return 'success'
        else:
            log("WARNING: Reservation may not have completed. Please check manually.")
            save_screenshot(driver, 'final_page')
            return 'error'

    except TimeoutException as e:
        log(f"ERROR: Timeout occurred - {str(e)}")
        try:
            save_screenshot(driver, 'error_timeout')
        except Exception:
            pass
        return 'error'
    except Exception as e:
        log(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        try:
            save_screenshot(driver, 'error_exception')
        except Exception:
            pass
        return 'error'
    finally:
        log("Closing browser...")
        try:
            driver.quit()
        except Exception:
            pass


def main():
    """Continuous polling loop — keeps trying until booking succeeds or target date passes."""
    log("=" * 60)
    log("Black Hawk Country Club - Tee Time Cancellation Poller")
    log("=" * 60)
    log(f"Headless mode: {HEADLESS}")
    log(f"Target date: {TARGET_DATE.strftime('%A, %B %d, %Y')}")
    log(f"Time window: {TARGET_TIME_START:.0f}:00 - {TARGET_TIME_END:.0f}:00")
    log(f"Course: {ALLOWED_COURSE_LABEL}")
    log(f"Players: {PLAYER_COUNTS}")
    log(f"Poll interval: {POLL_MIN_SECONDS/60:.0f}-{POLL_MAX_SECONDS/60:.0f} minutes (randomized)")
    log("=" * 60)

    attempt = 0
    while True:
        # Stop if the target date has passed
        if date.today() > TARGET_DATE:
            log("Target date has passed. Stopping.")
            sys.exit(0)

        attempt += 1
        log(f"\n{'='*40} Attempt #{attempt} {'='*40}")

        result = attempt_booking()

        if result == 'success':
            log("Booking completed successfully! Exiting.")
            sys.exit(0)

        # Pick a random wait time between 3-7 minutes
        wait_secs = random.uniform(POLL_MIN_SECONDS, POLL_MAX_SECONDS)
        log(f"Result: {result}. Waiting {wait_secs/60:.1f} minutes before next attempt...")
        time.sleep(wait_secs)

if __name__ == "__main__":
    main()
