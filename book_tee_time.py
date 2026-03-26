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
USERNAME = os.getenv('BHCC_USERNAME', 'alexander.dimitroff')
PASSWORD = os.getenv('BHCC_PASSWORD', 'Xovxeq-zusci8')
NUM_PLAYERS = 4
TARGET_TIME_START = 9  # 9 AM
TARGET_TIME_END = 10.5   # 10:30 AM
BOOKING_HOUR = 7  # Tee times open at 7 AM
BOOKING_MINUTE = 0
DAYS_AHEAD = int(os.getenv('DAYS_AHEAD', '8'))  # Book 8 days in advance by default

# Set to True when running on server (headless mode)
HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'

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

def book_tee_time():
    """Main function to book tee time"""
    log("Starting tee time booking automation...")

    result = should_book_today()
    if result is None:
        log("Nothing to book today. Exiting.")
        return True  # Not an error, just no booking scheduled

    target_date, time_start, time_end = result
    log(f"Target date: {target_date.strftime('%A, %B %d, %Y')}")
    log(f"Time window: {time_start}:00 - {time_end}:00")

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

        # Step 6: WAIT UNTIL 7:00 AM THEN CLICK SEARCH
        log("Form is ready. Preparing to search...")

        # Find the search button first (before waiting)
        search_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Search')]"))
        )
        log("Search button located, waiting for 7:00 AM...")

        # Wait until exactly 7:00 AM
        wait_until_booking_time()

        # CLICK IMMEDIATELY at 7:00 AM
        search_button.click()
        log("Clicked search button at " + datetime.now().strftime('%H:%M:%S.%f'))

        # Wait for results
        log("Waiting for search results to load...")
        time.sleep(3)
        log(f"Current URL after search: {driver.current_url}")
        save_screenshot(driver, 'after_search_click')

        # Wait for tee times to appear (up to 60 seconds)
        try:
            WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'span.time.ng-binding'))
            )
            log("Tee times loaded successfully!")
        except TimeoutException:
            log("Warning: Tee time elements took longer than expected to load...")
            save_screenshot(driver, 'search_timeout')
            time.sleep(10)
            page_text = driver.find_element(By.TAG_NAME, 'body').text
            log(f"Page text excerpt: {page_text[:500]}")

        # Screenshot the search results for debugging
        save_screenshot(driver, 'search_results')

        # Step 7: Find and click View for first available time in desired window
        log(f"Looking for tee times between {time_start}:00 and {time_end}:00...")

        time_spans = driver.find_elements(By.CSS_SELECTOR, 'span.time.ng-binding')
        view_buttons = driver.find_elements(By.XPATH, "//button[contains(@class, 'primary-btn') and contains(text(), 'View')]")

        found_time = False

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

        if not found_time:
            log("ERROR: No available tee times found in the target window!")
            save_screenshot(driver, 'no_times_available')
            return False

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
        return False
    except Exception as e:
        log(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        try:
            save_screenshot(driver, 'error_exception')
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
