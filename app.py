from flask import Flask, request, jsonify
from playwright.async_api import async_playwright
from playwright_stealth import stealth as playwright_stealth_func
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
    try:
        await playwright_stealth_func(page)
    except Exception as e:
        logging.warning(f"Stealth injection failed: {e}")

# --- PLAYWRIGHT ENGINE ---
async def run_playwright_test(test_data):
    results = []
    screenshot_base64 = None
    status = "SUCCESS"
    
    browser_choice = test_data.get('browser', 'chromium').lower()
    
    async with async_playwright() as p:
        browser_map = {"chromium": p.chromium, "firefox": p.firefox, "webkit": p.webkit}
        selected_engine = browser_map.get(browser_choice, p.chromium)
        
        browser = await selected_engine.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()
        await apply_playwright_stealth(page)
        
        try:
            test_payload = test_data.get('testCase') if isinstance(test_data.get('testCase'), dict) else test_data
            steps = test_payload.get('steps', [])
            
            for i, step in enumerate(steps):
                action = step.get('action', '').lower()
                t_desc = step.get('target_description', 'Element')
                value = step.get('data') or step.get('expected_value') or step.get('value', '')
                url = step.get('url') or value

                if action == 'navigate':
                    await page.goto(url, wait_until="domcontentloaded")
                    results.append(f"Step {i+1}: Navigated to {url}")

                elif action in ['type', 'fill']:
                    clean_name = t_desc.lower().replace(" box", "").strip()
                    loc = page.get_by_role("searchbox", name=clean_name, exact=False).or_(
                          page.get_by_role("textbox", name=clean_name, exact=False)).or_(
                          page.get_by_role("combobox", name=clean_name, exact=False)).first
                    
                    if await loc.count() == 0:
                        loc = page.locator(f"input[name*='{clean_name}'], input[id*='{clean_name}']").first

                    await loc.fill(value)
                    await page.keyboard.press("Enter")
                    results.append(f"Step {i+1}: Typed '{value}' into {t_desc}")
                    
                    # --- DOMAIN-AWARE GUARD ---
                    await asyncio.sleep(2)
                    if "google.com" in page.url.lower():
                        if await page.get_by_text("About this page", exact=False).is_visible():
                            raise Exception("BOT_BLOCKED: Google triggered a security challenge.")

                elif action == 'verify':
                    content = await page.content()
                    if value.lower() in content.lower():
                        results.append(f"Step {i+1}: Verified '{value}' is present.")
                    else:
                        raise Exception(f"Verification Failed: '{value}' not found.")

            # --- OPTIMIZED SCREENSHOT (The Fix) ---
            try:
                # full_page=False ensures we don't wait for infinite font loading
                screenshot_bytes = await page.screenshot(full_page=False, timeout=8000)
                screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            except:
                logging.warning("Screenshot timed out but logic passed.")

        except Exception as e:
            status = "FAILED"
            results.append(f"ERROR: {str(e)}")
        finally:
            await browser.close()
            
    return status, results, screenshot_base64

# --- API ROUTES ---
@app.route('/run-test', methods=['POST'])
def run_test():
    try:
        data = request.json
        status, logs, screenshot = asyncio.run(run_playwright_test(data))
        return jsonify({"status": status, "actualResults": "\n".join(logs), "screenshotBase64": screenshot})
    except Exception as e:
        return jsonify({"status": "ERROR", "actualResults": str(e)}), 500

@app.route('/')
def home():
    return "Pariksha Executor is LIVE!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
