from flask import Flask, request, jsonify
from playwright.async_api import async_playwright
import base64
import asyncio
import os
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

async def run_playwright_test(test_data):
    results = []
    screenshot_base64 = None
    page_source = None
    status = "SUCCESS"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        
        # ADDED: Stealth User-Agent to help avoid the Google "Sorry" page
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()
        
        try:
            test_payload = test_data.get('testCase') if isinstance(test_data.get('testCase'), dict) else test_data
            steps = test_payload.get('steps', [])
            
            for i, step in enumerate(steps):
                action = step.get('action', '').lower()
                if action in ['verify text', 'assert_text', 'verify']: 
                    action = 'verify'
                
                t_name = step.get('target_description', 'Element')
                selector = step.get('selector', '')
                value = step.get('data') or step.get('expected_value') or step.get('value', '')
                url = step.get('url') or value

                try:
                    if action == 'navigate':
                        await page.goto(url, wait_until="domcontentloaded")
                        results.append(f"Step {i+1}: Navigated to {url}")

                    elif action in ['type', 'fill']:
                        loc = None
                        if selector and selector != ':root':
                            loc = page.locator(selector)
                            if await loc.count() == 0: loc = None 
                        
                        if not loc:
                            clean_name = t_name.lower().replace(" box", "").replace(" field", "").strip()
                            loc = page.get_by_role("combobox", name=clean_name, exact=False).or_(
                                  page.get_by_role("textbox", name=clean_name, exact=False)).first
                        
                        await loc.fill(value)
                        await page.keyboard.press("Enter")
                        
                        # --- DETECTION PHASE (Inside the Type logic) ---
                        await asyncio.sleep(2) # Give the page a second to react
                        if "google.com/sorry" in page.url or await page.get_by_text("unusual traffic").is_visible():
                            page_source = await page.content()
                            raise Exception("BOT_BLOCKED: Google detected the script. Need Stealth/Proxy.")
                        # --- END DETECTION PHASE ---
                        
                        results.append(f"Step {i+1}: Typed '{value}' and verified no bot-block.")

                    elif action == 'click':
                        loc = page.locator(selector) if selector and selector != ':root' else page.get_by_role("button", name=t_name, exact=False).or_(page.get_by_text(t_name, exact=False)).first
                        await loc.click()
                        results.append(f"Step {i+1}: Clicked {t_name}")

                    elif action == 'verify':
                        await page.wait_for_selector(f"text={value}", timeout=8000)
                        results.append(f"Step {i+1}: Verified text '{value}' is present")

                except Exception as step_error:
                    page_source = await page.content()
                    raise Exception(f"Step {i+1} failed: {str(step_error)}")

            screenshot_bytes = await page.screenshot(full_page=True)
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

        except Exception as e:
            status = "FAILED"
            results.append(f"ERROR: {str(e)}")
            try:
                screenshot_bytes = await page.screenshot(full_page=True)
                screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                if not page_source: page_source = await page.content()
            except: pass
        finally:
            await browser.close()
            
    return status, results, screenshot_base64, page_source

@app.route('/run-test', methods=['POST'])
def run_test():
    try:
        data = request.json
        status, logs, screenshot, html_dump = asyncio.run(run_playwright_test(data))
        return jsonify({
            "status": status,
            "actualResults": "\n".join(logs),
            "screenshotBase64": screenshot,
            "pageSource": html_dump
        })
    except Exception as e:
        return jsonify({"status": "ERROR", "actualResults": str(e)}), 500

@app.route('/')
def home():
    return "Pariksha Executor is LIVE!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
