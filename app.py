from flask import Flask, request, jsonify
from playwright.async_api import async_playwright
import playwright_stealth
import selenium_stealth

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import base64
import asyncio
import os
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# --- HELPER: Safe Stealth Injection ---
async def apply_playwright_stealth(page):
    """Ensures Ghost-Runner Armor is applied correctly regardless of module structure."""
    try:
        if hasattr(playwright_stealth, 'stealth'):
            func = playwright_stealth.stealth
            if not callable(func) and hasattr(func, 'stealth'):
                func = func.stealth
            await func(page)
    except Exception as e:
        logging.warning(f"Playwright Stealth injection failed: {e}")

# --- PLAYWRIGHT ENGINE ---
async def run_playwright_test(test_data):
    results = []
    screenshot_base64, page_source = None, None
    status = "SUCCESS"
    
    # Get browser choice from payload, default to chromium
    browser_choice = test_data.get('browser', 'chromium').lower()
    
    async with async_playwright() as p:
        # Browser Buffet: Ready for anything, defaults to Google engine
        browser_map = {
            "chromium": p.chromium,
            "firefox": p.firefox,
            "webkit": p.webkit
        }
        selected_engine = browser_map.get(browser_choice, p.chromium)
        
        browser = await selected_engine.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()
        
        # Apply Stealth Armor
        await apply_playwright_stealth(page)
        
        try:
            test_payload = test_data.get('testCase') if isinstance(test_data.get('testCase'), dict) else test_data
            steps = test_payload.get('steps', [])
            
            for i, step in enumerate(steps):
                action = step.get('action', '').lower()
                t_description = step.get('target_description', 'Element')
                selector = step.get('selector', '')
                value = step.get('data') or step.get('expected_value') or step.get('value', '')
                url = step.get('url') or value

                if action == 'navigate':
                    await page.goto(url, wait_until="domcontentloaded")
                    results.append(f"Step {i+1}: Navigated to {url}")

                elif action in ['type', 'fill']:
                    # --- UNIVERSAL SMART LOCATOR ---
                    clean_name = t_description.lower().replace(" box", "").strip()
                    
                    # Search for any valid input role: searchbox, textbox, or combobox
                    loc = page.get_by_role("searchbox", name=clean_name, exact=False).or_(
                          page.get_by_role("textbox", name=clean_name, exact=False)).or_(
                          page.get_by_role("combobox", name=clean_name, exact=False)).first
                    
                    # Fallback: Search for name or ID directly if roles aren't defined
                    if await loc.count() == 0:
                        loc = page.locator(f"input[name*='{clean_name}'], input[id*='{clean_name}']").first

                    await loc.fill(value)
                    await page.keyboard.press("Enter")
                    results.append(f"Step {i+1}: Typed '{value}' into {t_description}")
                    
                    # --- DOMAIN-AWARE SMART GUARD ---
                    await asyncio.sleep(2)
                    is_blocked = False
                    current_url = page.url.lower()

                    if "google.com" in current_url:
                        # Panic mode ONLY for Google's specific bot walls
                        if "google.com/sorry" in current_url or \
                           await page.get_by_text("unusual traffic", exact=False).is_visible() or \
                           await page.get_by_text("About this page", exact=False).is_visible():
                            is_blocked = True
                    
                    # General safety check for other sites
                    elif await page.get_by_role("checkbox", name="I'm not a robot").is_visible():
                        is_blocked = True

                    if is_blocked:
                        raise Exception("BOT_BLOCKED: Security challenge detected.")

                elif action == 'click':
                    loc = page.locator(selector) if selector and selector != ':root' else \
                          page.get_by_role("button", name=t_description, exact=False).or_(
                          page.get_by_text(t_description, exact=False)).first
                    await loc.click()
                    results.append(f"Step {i+1}: Clicked {t_description}")

                elif action == 'verify':
                    content = await page.content()
                    if value.lower() in content.lower():
                        results.append(f"Step {i+1}: Verified '{value}' is present.")
                    else:
                        raise Exception(f"Verification Failed: '{value}' not found.")

            # Capture Final Proof
            screenshot_bytes = await page.screenshot(full_page=True)
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            
        except Exception as e:
            status = "FAILED"
            results.append(f"ERROR: {str(e)}")
            # Try to get a screenshot even on failure
            try:
                screenshot_bytes = await page.screenshot(full_page=True)
                screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            except:
                pass
        finally:
            await browser.close()
            
    return status, results, screenshot_base64

# --- SELENIUM FALLBACK ENGINE ---
def run_selenium_test(test_data):
    results, status = [], "SUCCESS"
    screenshot_base64 = None
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        selenium_stealth.stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)
        
        test_payload = test_data.get('testCase') if isinstance(test_data.get('testCase'), dict) else test_data
        steps = test_payload.get('steps', [])
        
        for i, step in enumerate(steps):
            action = step.get('action', '').lower()
            url = step.get('url') or step.get('data', '')
            if action == 'navigate':
                driver.get(url)
                results.append(f"Step {i+1}: (Selenium) Navigated to {url}")

        screenshot_bytes = driver.get_screenshot_as_png()
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
    except Exception as e:
        status = "FAILED"
        results.append(f"Selenium ERROR: {str(e)}")
    finally:
        driver.quit()
        
    return status, results, screenshot_base64

@app.route('/run-test', methods=['POST'])
def run_test():
    try:
        data = request.json
        executor_type = data.get('executor_type', 'playwright').lower()
        
        if executor_type == 'selenium':
            status, logs, screenshot = run_selenium_test(data)
        else:
            status, logs, screenshot = asyncio.run(run_playwright_test(data))
        
        return jsonify({
            "status": status,
            "actualResults": "\n".join(logs),
            "screenshotBase64": screenshot
        })
    except Exception as e:
        return jsonify({"status": "ERROR", "actualResults": str(e)}), 500

@app.route('/')
def home():
    return "Pariksha Multi-Engine Executor is LIVE!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
