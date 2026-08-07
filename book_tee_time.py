#!/usr/bin/env python3
"""
Black Hawk Country Club Tee Time Booking Automation
Books tee times between 9-10:30 AM when they open at 7 AM (8 days ahead)
Reads target dates from booking_config.json — runs daily, only books when scheduled.
Uses undetected-chromedriver to bypass bot detection.
"""

import os
import sys
import time
import json
import logging
import subprocess
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException

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
if not USERNAME or not PASSWORD:
    raise SystemExit("BHCC_USERNAME and BHCC_PASSWORD must be set in .env")
NUM_PLAYERS = 4
TARGET_TIME_START = 9  # 9 AM
TARGET_TIME_END = 10.5   # 10:30 AM
BOOKING_HOUR = 7  # Tee times open at 7 AM
BOOKING_MINUTE = 0
DAYS_AHEAD = int(os.getenv('DAYS_AHEAD', '8'))  # Book 8 days in advance by default
# How many minutes before 7:00 AM to start logging in. On a cloud runner the job
# may start many minutes early, so we deliberately hold off on login until just
# before the drop — this keeps the ezlinks session fresh right up to the click.
LOGIN_LEAD_MINUTES = int(os.getenv('LOGIN_LEAD_MINUTES', '3'))

# How long to keep re-running the search after the 7:00 AM drop before giving
# up, and how long to pause between attempts. On 2026-08-07 the search clicked
# at 7:00:00.08 came back "0 tee times" for the whole day with a stuck
# "Please Wait..." spinner — right at the drop the site lags under load and
# inventory can post seconds-to-minutes late — and the bot's single search
# meant it walked away while slots were appearing. Re-searching is what wins.
SEARCH_RETRY_MINUTES = float(os.getenv('SEARCH_RETRY_MINUTES', '30'))
SEARCH_RETRY_PAUSE_SECONDS = float(os.getenv('SEARCH_RETRY_PAUSE_SECONDS', '10'))

# Set to True when running on server (headless mode)
HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'

# Dry run: log in, open the booking page, run a search and list the available
# times — but STOP before reserving anything. Ignores the day/time schedule and
# the 7:00 AM wait so you can validate login + navigation on any day. Set via the
# DRY_RUN env var (used by the workflow's manual "Run workflow" button).
DRY_RUN = os.getenv('DRY_RUN', 'false').lower() == 'true'

# Config file for scheduled target dates.
# Prefer project root config, then fallback to logs/ for backwards compatibility.
PRIMARY_CONFIG_FILE = os.path.join(SCRIPT_DIR, 'booking_config.json')
FALLBACK_CONFIG_FILE = os.path.join(LOG_DIR, 'booking_config.json')

def load_booking_config():
    """Load booking configuration from shared config file"""
    for config_path in (PRIMARY_CONFIG_FILE, FALLBACK_CONFIG_FILE):
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                log(f"Warning: Could not read config file {config_path}: {e}")
    return None

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

def calculate_target_date():
    """Calculate the target date (DAYS_AHEAD days from now)."""
    today = datetime.now()
    target = today + timedelta(days=DAYS_AHEAD)
    return target

def should_book_today():
    """
    Check if today is a scheduled booking day.
    Returns (target_date, time_start, time_end) if we should book, or None to skip.
    Checks both one-off target_dates and recurring day-of-week entries.
    """
    target = calculate_target_date()
    target_str = target.strftime('%Y-%m-%d')
    target_day = target.strftime('%A').lower()
    config = load_booking_config()

    if not config:
        log(f"No config file found. Booking for {target_str} ({target.strftime('%A')}) with default time window.")
        return target, TARGET_TIME_START, TARGET_TIME_END

    # Recurring day rules (ex: friday, saturday)
    for entry in config.get('recurring', []):
        if entry.get('day', '').lower() == target_day:
            t_start = entry.get('time_start', TARGET_TIME_START)
            t_end = entry.get('time_end', TARGET_TIME_END)
            log(f"Recurring {target_day} booking: {target_str} (time window {t_start}-{t_end})")
            return target, t_start, t_end

    # One-off dates
    if target_str in config.get('target_dates', []):
        log(f"Scheduled booking found: {target_str} ({target.strftime('%A')})")
        return target, TARGET_TIME_START, TARGET_TIME_END

    log(f"No booking scheduled for {target_str} ({target.strftime('%A')}). Skipping.")
    return None

def wait_until_login_time():
    """
    Hold off until LOGIN_LEAD_MINUTES before 7:00 AM before we log in.

    Cloud schedulers (e.g. GitHub Actions) can start a job several minutes
    early or late, so we don't want to log in the moment the runner boots and
    then sit on a stale session for 20+ minutes. Instead we sleep until just
    before the drop, log in fresh, and let wait_until_booking_time() handle the
    final precise wait. Returns immediately if we're already inside the window.
    """
    now = datetime.now()
    login_target = now.replace(hour=BOOKING_HOUR, minute=BOOKING_MINUTE,
                               second=0, microsecond=0) - timedelta(minutes=LOGIN_LEAD_MINUTES)

    if now >= login_target:
        log(f"Already within {LOGIN_LEAD_MINUTES} min of {BOOKING_HOUR}:00 AM, logging in now...")
        return

    wait_seconds = (login_target - now).total_seconds()
    log(f"Waiting {wait_seconds:.0f}s until {login_target.strftime('%H:%M:%S')} "
        f"({LOGIN_LEAD_MINUTES} min before the drop) to begin login...")
    time.sleep(wait_seconds)
    log("Login window reached — starting login now.")

def wait_until_booking_time():
    """
    Wait until exactly 7:00:00 AM to click search.
    Returns immediately if already past 7 AM.
    """
    now = datetime.now()
    target_time = now.replace(hour=BOOKING_HOUR, minute=BOOKING_MINUTE, second=0, microsecond=0)

    if now >= target_time:
        log(f"Already past {BOOKING_HOUR}:00 AM, proceeding immediately...")
        return

    wait_seconds = (target_time - now).total_seconds()
    log(f"Waiting {wait_seconds:.1f} seconds until {BOOKING_HOUR}:00:00 AM...")

    # Wait until 1 second before, then do precise timing
    if wait_seconds > 1:
        time.sleep(wait_seconds - 1)

    # Precise wait for the final second
    while datetime.now() < target_time:
        time.sleep(0.01)  # 10ms precision

    log(f"It's {BOOKING_HOUR}:00 AM - GO!")

def save_screenshot(driver, name):
    """Save a screenshot with timestamp to the screenshots directory"""
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    filename = f'{name}_{timestamp}.png'
    filepath = os.path.join(SCREENSHOT_DIR, filename)
    driver.save_screenshot(filepath)
    log(f"Screenshot saved: {filepath}")
    return filepath

def save_page_source(driver, name):
    """Dump the current page HTML so selector breakage is diagnosable later.

    A screenshot shows *that* something looks wrong; the HTML shows *why* (e.g.
    the button's id/class changed). Saved next to the screenshots so it rides
    along in the uploaded artifact. Never raises — diagnostics must not mask the
    original error.
    """
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        filepath = os.path.join(SCREENSHOT_DIR, f'{name}_{timestamp}.html')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        log(f"Page HTML saved: {filepath}  (current URL: {driver.current_url})")
        return filepath
    except Exception as e:
        log(f"Could not save page HTML ({name}): {e}")
        return None

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

def set_search_date(driver, target_date_str):
    """Set the search date through Angular's $scope.

    The form is the new ezlinks Angular SPA where ec.startDate is a STRING in
    MM/DD/YYYY format. Typing into the input + Enter triggers an immediate
    search before we want it (the form's submit handler runs on Enter), so we
    bypass typing entirely and assign the model.
    """
    return driver.execute_script(
        """
        var dateStr = arguments[0];
        var input = document.getElementById('dateInput');
        if (!input) return {err: 'no-input'};
        if (!window.angular) return {err: 'no-angular'};
        var scope = angular.element(input).scope();
        if (!scope || !scope.ec) return {err: 'no-scope-ec'};
        scope.$apply(function() {
            scope.ec.startDate = dateStr;
            if (typeof scope.ec.onDateChanged === 'function') {
                scope.ec.onDateChanged(scope.ec.startDate);
            }
        });
        return {
            ok: true,
            startDate: String(scope.ec.startDate || ''),
            enableSearchButton: !!scope.ec.enableSearchButton
        };
        """,
        target_date_str,
    )

def rerun_search(driver, target_date_str):
    """Reload the booking page and run a fresh search.

    Reload rather than re-click in place: the results page can wedge on its
    "Please Wait..." spinner and never recover without a fresh page. The SSO
    redirect reuses the logged-in bhawkcc session, so this lands straight on
    preSearch. Returns True if the search was re-run, False if the page never
    became ready (caller should just try again).
    """
    driver.get('https://www.bhawkcc.com/club/scripts/interfaces/ezlinks.asp')
    time.sleep(3)
    try:
        WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'input#dateInput'))
        )
    except TimeoutException:
        log("Warning: Date input not ready on retry; will reload and try again...")
        return False
    set_search_date(driver, target_date_str)
    time.sleep(1)
    try:
        search_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//button[contains(normalize-space(.), 'Search All')]",
            ))
        )
    except TimeoutException:
        log("Warning: Search All button not found on retry; will reload and try again...")
        return False
    try:
        search_button.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", search_button)
    log("Re-ran search at " + datetime.now().strftime('%H:%M:%S.%f'))
    return True

def book_tee_time():
    """Main function to book tee time"""
    log("Starting tee time booking automation...")

    result = should_book_today()
    if result is None:
        if DRY_RUN:
            # No real booking scheduled, but in a dry run we still want to
            # exercise login + navigation. Target the far edge of the booking
            # window (today + DAYS_AHEAD) with a full-day time window.
            target = calculate_target_date()
            result = (target, 0, 24)
            log(f"DRY_RUN: nothing scheduled today; testing navigation for "
                f"{target.strftime('%A, %B %d, %Y')} with a full-day window.")
        else:
            log("Nothing to book today. Exiting.")
            return True  # Not an error, just no booking scheduled

    target_date, time_start, time_end = result
    log(f"Target date: {target_date.strftime('%A, %B %d, %Y')}")
    log(f"Time window: {time_start}:00 - {time_end}:00")
    if DRY_RUN:
        log("*** DRY RUN — will search and list times but NOT reserve anything. ***")

    # Hold off on login until just before 7:00 AM so the session stays fresh.
    # Skipped in a dry run so the test doesn't hang until the morning.
    if not DRY_RUN:
        wait_until_login_time()

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

        # Step 3: Navigate directly to ezlinks SSO endpoint in the same tab.
        # The site's "Book A Tee Time" link uses target="_blank" + a JS popup
        # which is fragile to drive. Direct GET on ezlinks.asp triggers the
        # SSO redirect to houstonmemberbh.ezlinksgolf.com#/preSearch with the
        # logged-in session, and avoids tab-handle bookkeeping entirely.
        log("Navigating directly to ezlinks booking page (SSO redirect)...")
        driver.get('https://www.bhawkcc.com/club/scripts/interfaces/ezlinks.asp')
        time.sleep(5)
        log(f"Booking page URL: {driver.current_url}")

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

        # Step 5: Set the date through Angular's $scope (see set_search_date).
        target_date_str = target_date.strftime('%m/%d/%Y')
        log(f"Setting ec.startDate = {target_date_str} via $scope")
        result = set_search_date(driver, target_date_str)
        log(f"Scope set result: {result}")
        time.sleep(1.5)
        save_screenshot(driver, 'after_date_set')

        # Step 6: Wait until 7:00 AM, then click Search All exactly once.
        log("Locating Search All button...")
        search_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//button[contains(normalize-space(.), 'Search All')]",
            ))
        )
        if DRY_RUN:
            log("DRY_RUN: skipping the 7:00 AM wait — searching immediately.")
        else:
            log("Search button ready, waiting for 7:00 AM...")
            wait_until_booking_time()

        try:
            search_button.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", search_button)
        log("Clicked search at " + datetime.now().strftime('%H:%M:%S.%f'))

        # Step 7: Find a time in the desired window, RE-RUNNING the search
        # until one appears or the retry window closes. A single search right
        # at 7:00:00 routinely comes back empty (site lagging under the drop
        # rush, inventory posting late), so walking away after one look loses
        # the morning — see the 2026-08-07 run.
        retry_deadline = datetime.now() + timedelta(minutes=SEARCH_RETRY_MINUTES)
        attempt = 0
        found_time = False

        while True:
            attempt += 1

            # Wait for results
            log("Waiting for search results to load...")
            time.sleep(3)
            log(f"Current URL after search: {driver.current_url}")
            if attempt == 1:
                save_screenshot(driver, 'after_search_click')

            # Wait for tee times to appear
            try:
                WebDriverWait(driver, 60 if attempt == 1 else 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'span.time.ng-binding'))
                )
                log("Tee times loaded successfully!")
            except TimeoutException:
                log("Warning: Tee time elements took longer than expected to load...")
                if attempt == 1:
                    save_screenshot(driver, 'search_timeout')
                    save_page_source(driver, 'search_timeout')
                    time.sleep(10)
                    page_text = driver.find_element(By.TAG_NAME, 'body').text
                    log(f"Page text excerpt: {page_text[:500]}")

            if attempt == 1:
                # Screenshot the search results for debugging
                save_screenshot(driver, 'search_results')

            log(f"Looking for tee times between {time_start}:00 and {time_end}:00 "
                f"(attempt {attempt})...")

            time_spans = driver.find_elements(By.CSS_SELECTOR, 'span.time.ng-binding')

            # In a dry run, report what we found and stop before reserving
            # anything — no retry loop, one look is the point of the test.
            if DRY_RUN:
                found_times = [s.text.strip() for s in time_spans if s.text.strip()]
                if found_times:
                    log(f"DRY RUN SUCCESS: login + navigation + search all worked. "
                        f"Found {len(found_times)} tee times: {', '.join(found_times)}")
                else:
                    log("DRY RUN: reached the results page but found no listed times "
                        "(could be a date with no availability). Check the screenshot.")
                save_screenshot(driver, 'dry_run_results')
                return True

            view_buttons = driver.find_elements(By.XPATH, "//button[contains(@class, 'primary-btn') and contains(text(), 'View')]")

            for i, time_span in enumerate(time_spans):
                try:
                    time_text = time_span.text.strip()

                    # Parse the time
                    time_obj = datetime.strptime(time_text, '%I:%M %p')
                    hour_decimal = time_obj.hour + time_obj.minute / 60.0

                    # Check if time is in target window
                    if time_start <= hour_decimal < time_end:
                        log(f"Found available time: {time_text}")

                        # Click the corresponding View button
                        if i < len(view_buttons):
                            view_buttons[i].click()
                            found_time = True
                            time.sleep(3)
                            break
                except Exception as e:
                    log(f"Error parsing time at index {i}: {e}")
                    continue

            if found_time:
                break

            if datetime.now() >= retry_deadline:
                log(f"ERROR: No available tee times found in the target window "
                    f"after {attempt} search attempts over {SEARCH_RETRY_MINUTES:g} minutes!")
                save_screenshot(driver, 'no_times_available')
                save_page_source(driver, 'no_times_available')
                return False

            log(f"No times in the window yet ({len(time_spans)} listed overall). "
                f"Re-running the search in {SEARCH_RETRY_PAUSE_SECONDS:g}s...")
            time.sleep(SEARCH_RETRY_PAUSE_SECONDS)
            # If the reload itself wedges, loop back around — the deadline
            # check above still bounds the total time spent.
            rerun_search(driver, target_date_str)

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
            return False
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
            return False
        time.sleep(3)

        # Step 10: Click Finish Reservation
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
            return False
        time.sleep(3)

        # Step 11: Verify success
        time.sleep(2)
        page_content = driver.page_source.lower()

        if 'reservation complete' in page_content or 'confirmation' in page_content or 'thank you' in page_content:
            log("SUCCESS! Tee time reservation completed!")
            save_screenshot(driver, 'reservation_confirmation')
            return True
        else:
            log("WARNING: Reservation may not have completed. Please check manually.")
            save_screenshot(driver, 'final_page')
            return False

    except TimeoutException as e:
        log(f"ERROR: Timeout occurred - {str(e)}")
        save_screenshot(driver, 'error_timeout')
        save_page_source(driver, 'error_timeout')
        return False
    except Exception as e:
        log(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        try:
            save_screenshot(driver, 'error_exception')
            save_page_source(driver, 'error_exception')
        except Exception:
            pass
        return False
    finally:
        log("Closing browser...")
        time.sleep(2)
        driver.quit()

def main():
    """Main entry point"""
    log("=" * 60)
    log("Black Hawk Country Club - Tee Time Booking Bot")
    log("=" * 60)
    log(f"Headless mode: {HEADLESS}")
    log(f"DAYS_AHEAD: {DAYS_AHEAD}")

    config = load_booking_config()
    if config and 'recurring' in config:
        for entry in config.get('recurring', []):
            log(f"Recurring: {entry.get('day')} (time {entry.get('time_start')}-{entry.get('time_end')})")
    if config and 'target_dates' in config and config['target_dates']:
        log(f"Scheduled dates: {', '.join(sorted(config['target_dates']))}")
    else:
        log("No scheduled one-off dates configured.")

    success = book_tee_time()

    if success:
        log("Booking completed successfully!")
        sys.exit(0)
    else:
        log("Booking failed. Please check the logs above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
