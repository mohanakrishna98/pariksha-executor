from flask import Flask, request, jsonify
from playwright.async_api import async_playwright
import playwright_stealth  # Import the module directly

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import selenium_stealth  # Import the module directly

import base64
import asyncio
import os
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# --- PLAYWRIGHT ENGINE ---
async def run_playwright_test(test_data):
    results = []
    screenshot_base64, page_source = None, None
    status = "SUCCESS"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()
        
        # APPLY STEALTH: Using the explicit module.function path
        try:
            await playwright_stealth.stealth(page)
        except Exception as e:
            logging.warning(f"Stealth injection failed: {e}")
        
        try:
            test_payload = test_data.get('testCase') if isinstance(test_data.get('testCase'), dict) else test_data
            steps = test_payload.get('steps', [])
            
            for i, step in enumerate(steps):
                action = step.get('action', '').lower()
                t_name = step.get('target_description', 'Element')
                selector = step.get('selector', '')
                value = step.get('data') or step.get('expected_value') or step.get('value', '')
                url = step.get('url') or value

                if action == 'navigate':
                    await page.goto(url, wait_until="domcontentloaded")
                    results.append(f"Step {i+1}: Navigated to {url}")
                elif action in ['type', 'fill']:
                    # Mohan-proof Smart Locator
                    clean_name = t_name.lower().replace(" box", "").strip()
                    loc = page.get_by_role("combobox", name=clean_name, exact=False).first
                    await loc.fill(value)
                    await page.keyboard.press("Enter")
                    
                    # Bot Detection Phase
                    await asyncio.sleep(2)
                    if "google.com/sorry" in page.url:
                        raise Exception("BOT_BLOCKED: Google detected the script.")
                    results.append(f"Step {i+1}: Typed '{value}'")

            screenshot_bytes = await page.screenshot(full_page=True)
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        except Exception as e:
            status = "FAILED"
            results.append(f"ERROR: {str(e)}")
            page_source = await page.content()
        finally:
            await browser.close()
            
    return status, results, screenshot_base64, page_source

# --- SELENIUM ENGINE ---
def run_selenium_test(test_data):
    results = []
    screenshot_base64, page_source = None, None
    status = "SUCCESS"
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    # APPLY STEALTH: Using the explicit module.function path
    try:
        selenium_stealth.stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )
    except Exception as e:
        logging.warning(f"Selenium Stealth injection failed: {e}")
    
    try:
        test_payload = test_data.get('testCase') if isinstance(test_data.get('testCase'), dict) else test_data
        steps = test_payload.get('steps', [])
        
        for i, step in enumerate(steps):
            action = step.get('action', '').lower()
            url = step.get('url') or step.get('data', '')
            
            if action == 'navigate':
                driver.get(url)
                if "google.com/sorry" in driver.current_url:
                    raise Exception("BOT_BLOCKED: Selenium detected.")
                results.append(f"Step {i+1}: (Selenium) Navigated to {url}")

        screenshot_bytes = driver.get_screenshot_as_png()
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
    except Exception as e:
        status = "FAILED"
        results.append(f"Selenium ERROR: {str(e)}")
        page_source = driver.page_source
    finally:
        driver.quit()
        
    return status, results, screenshot_base64, page_source

@app.route('/run-test', methods=['POST'])
def run_test():
    try:
        data = request.json
        executor_type = data.get('executor_type', 'playwright').lower()
        
        if executor_type == 'selenium':
            status, logs, screenshot, html = run_selenium_test(data)
        else:
            status, logs, screenshot, html = asyncio.run(run_playwright_test(data))
        
        return jsonify({
            "status": status,
            "actualResults": "\n".join(logs),
            "screenshotBase64": screenshot,
            "pageSource": html
        })
    except Exception as e:
        return jsonify({"status": "ERROR", "actualResults": str(e)}), 500

@app.route('/')
def home():
    return "Pariksha Multi-Engine Executor is LIVE!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
