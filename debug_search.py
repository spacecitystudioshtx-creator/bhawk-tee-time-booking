#!/usr/bin/env python3
"""
Debug script to see what happens after clicking search
"""

import os
from datetime import datetime
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

USERNAME = os.getenv('BHCC_USERNAME', 'alexander.dimitroff')
PASSWORD = os.getenv('BHCC_PASSWORD', 'Xovxeq-zusci8')

def debug_search():
    """Debug the search functionality"""
    target_date = datetime(2026, 2, 5)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        
        try:
            # Login
            print("Logging in...")
            page.goto('https://www.bhawkcc.com/about-black-hawk-country-club/login?E=3', timeout=30000)
            page.wait_for_timeout(2000)
            page.fill('input#login_username_main', USERNAME)
            page.fill('input#login_password_main', PASSWORD)
            page.click('button#login_submit_main')
            page.wait_for_timeout(3000)
            
            # Open menu and click booking
            print("Opening menu...")
            page.click('div.nav-trigger')
            page.wait_for_timeout(1500)
            
            print("Clicking Book A Tee Time...")
            with context.expect_page() as new_page_info:
                page.evaluate('''() => {
                    const link = document.querySelector('a[href="/club/scripts/interfaces/ezlinks.asp"]');
                    if (link) link.click();
                }''')
            
            new_page = new_page_info.value
            new_page.wait_for_load_state('domcontentloaded', timeout=30000)
            page = new_page
            page.wait_for_timeout(3000)
            
            # Fill in search
            print("Filling in search form...")
            date_input = page.locator('input#dateInput')
            date_input.click()
            page.wait_for_timeout(1500)
            date_input.fill('02/05/2026')
            page.wait_for_timeout(1500)
            
            # Click day in calendar
            print("Clicking day 5 in calendar...")
            page.locator('a.ui-state-default:has-text("5")').first.click()
            page.wait_for_timeout(1000)
            
            print("Selecting Richmond...")
            page.click('label:has-text("Richmond")')
            page.wait_for_timeout(1000)
            
            print("Selecting Black Hawk...")
            page.click('label:has-text("Black Hawk Country Club")')
            page.wait_for_timeout(1000)
            
            print("Clicking Search button...")
            page.click('button.btn-default:has-text("Search")')
            
            print("\n=== AFTER CLICKING SEARCH ===")
            print("Waiting 10 seconds to see what loads...")
            page.wait_for_timeout(10000)
            
            # Take screenshot
            page.screenshot(path='after_search.png')
            print("Screenshot saved: after_search.png")
            
            # Check what's on the page
            print("\n=== PAGE CONTENT ANALYSIS ===")
            
            # Check for loading indicators
            loading_elements = page.locator('.loading, .spinner, .ng-loading, [ng-show*="loading"]')
            print(f"Loading indicators found: {loading_elements.count()}")
            
            # Check for time spans
            time_spans = page.locator('span.time.ng-binding')
            print(f"Time spans found: {time_spans.count()}")
            
            # Check for view buttons
            view_buttons = page.locator('button.primary-btn:has-text("View")')
            print(f"View buttons found: {view_buttons.count()}")
            
            # Check for error messages
            errors = page.locator('.error, .alert, [class*="error"]')
            print(f"Error elements found: {errors.count()}")
            if errors.count() > 0:
                print(f"Error text: {errors.first.inner_text()}")
            
            # Check page URL
            print(f"Current URL: {page.url}")
            
            # Save page HTML
            with open('after_search.html', 'w', encoding='utf-8') as f:
                f.write(page.content())
            print("HTML saved: after_search.html")
            
            print("\n=== Keeping browser open for 30 seconds for manual inspection ===")
            page.wait_for_timeout(30000)
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()

if __name__ == "__main__":
    debug_search()
