from flask import Flask, request, jsonify
from playwright.async_api import async_playwright
import base64
import asyncio
import os
import logging

app = Flask(__name__)
# Set up logging so you can see errors in the Render "Logs" tab
logging.basicConfig(level=logging.DEBUG)

async def run_playwright_test(test_data):
    results = []
    screenshot_base64 = None
    status = "SUCCESS"
    
    async with async_playwright() as p:
        # Args to help run in low-memory environments like Render Free Tier
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(viewport={'width': 1280, 'height': 720})
        page = await context.new_page()
        
        try:
            # Handle the nested 'testCase' structure found in your logs
            test_payload = test_data.get('testCase') or test_data
            steps = test_payload.get('steps', [])
            
            for i, step in enumerate(steps):
                # Standardize common action names
                action = step.get('action', '').lower()
                if action == 'assert_text': action = 'verify'
                
                # Fixed: Consistency in variable names
                t_name = step.get('target_description', 'Element')
                selector = step.get('selector', '')
                value = step.get('data') or step.get('expected_value') or step.get('value', '')
                
                if action == 'navigate':
                    url = step.get('url') or value
                    await page.goto(url, wait_until="domcontentloaded")
                    results.append(f"Step {i+1}: Navigated to {url}")

                elif action in ['type', 'fill']:
                    # Use selector if provided and valid, otherwise use the smart role logic
                    if selector and selector != ':root':
                        loc = page.locator(selector)
                    else:
                        loc = page.get_by_role("combobox", name=t_name, exact=False).or_(
                              page.get_by_role("textbox", name=t_name, exact=False)).first
                    
                    await loc.fill(value)
                    # FIXED: Used 't_name' consistently here
                    results.append(f"Step {i+1}: Typed '{value}' into {t_name}")

                elif action == 'click':
                    if selector and selector != ':root':
                        loc = page.locator(selector)
                    else:
                        loc = page.get_by_role("button", name=t_name, exact=False).or_(
                              page.get_by_text(t_name, exact=False)).first
                    
                    await loc.click()
                    results.append(f"Step {i+1}: Clicked {t_name}")

                elif action == 'verify':
                    await page.wait_for_selector(f"text={value}", timeout=5000)
                    results.append(f"Step {i+1}: Verified text '{value}' is present")

            # Capture final success screenshot
            screenshot_bytes = await page.screenshot(full_page=True)
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

        except Exception as e:
            status = "FAILED"
            results.append(f"Step FAILED: {str(e)}")
            # Capture error screenshot
            try:
                screenshot_bytes = await page.screenshot(full_page=True)
                screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            except:
                pass
        finally:
            await browser.close()
            
    return status, results, screenshot_base64

@app.route('/run-test', methods=['POST'])
def run_test():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No JSON payload received"}), 400
            
        # Run the async logic
        status, logs, screenshot = asyncio.run(run_playwright_test(data))
        
        return jsonify({
            "status": status,
            "actualResults": "\n".join(logs),
            "screenshotBase64": screenshot
        })
    except Exception as e:
        # This will now print the REAL error to your Render Logs
        app.logger.error(f"CRITICAL ERROR: {str(e)}")
        return jsonify({"status": "ERROR", "actualResults": f"Server Crash: {str(e)}"}), 500

@app.route('/')
def home():
    return "Pariksha Executor is LIVE and ready for tests!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
