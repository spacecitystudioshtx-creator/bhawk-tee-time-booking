#!/usr/bin/env python3
"""
Diagnostic script to explore Black Hawk CC website and find correct selectors
"""

from playwright.sync_api import sync_playwright
import time

def diagnose_website():
    """Explore the website structure"""
    print("Starting website diagnosis...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=1000)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
        )
        page = context.new_page()
        
        try:
            # Navigate to homepage
            print("\n1. Loading homepage...")
            page.goto('https://www.bhawkcc.com/', timeout=60000)
            page.wait_for_load_state('networkidle', timeout=30000)
            time.sleep(3)
            
            print("\n2. Taking screenshot of homepage...")
            page.screenshot(path='homepage.png')
            print("   Saved as: homepage.png")
            
            # Try to find login-related elements
            print("\n3. Searching for login elements...")
            
            # Check for various login possibilities
            login_possibilities = [
                "text=Login",
                "text=Log In", 
                "text=Sign In",
                "text=Member Login",
                "a:has-text('Login')",
                "a:has-text('Log In')",
                "button:has-text('Login')",
                "[href*='login']",
                "[href*='member']",
                ".login",
                "#login",
            ]
            
            for selector in login_possibilities:
                try:
                    element = page.locator(selector).first
                    if element.count() > 0:
                        print(f"   ✓ Found: {selector}")
                        print(f"     Text: {element.inner_text()}")
                        print(f"     Visible: {element.is_visible()}")
                except:
                    pass
            
            # Get all links on the page
            print("\n4. All links on homepage:")
            links = page.locator('a')
            for i in range(min(links.count(), 20)):  # First 20 links
                try:
                    href = links.nth(i).get_attribute('href')
                    text = links.nth(i).inner_text()
                    if text.strip():
                        print(f"   - {text[:50]} -> {href}")
                except:
                    pass
            
            # Look for menu/navigation
            print("\n5. Looking for menu buttons...")
            menu_possibilities = [
                "button",
                "[class*='menu']",
                "[class*='nav']",
                "[aria-label*='menu']",
                "text=☰",
            ]
            
            for selector in menu_possibilities:
                try:
                    elements = page.locator(selector)
                    if elements.count() > 0:
                        print(f"   Found {elements.count()} elements matching: {selector}")
                except:
                    pass
            
            print("\n6. Page HTML structure saved to page_structure.html")
            with open('page_structure.html', 'w', encoding='utf-8') as f:
                f.write(page.content())
            
            print("\n7. Waiting 10 seconds for you to manually explore...")
            print("   Look at the browser window and note where the login button is")
            time.sleep(10)
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("\nClosing browser...")
            browser.close()

if __name__ == "__main__":
    diagnose_website()
