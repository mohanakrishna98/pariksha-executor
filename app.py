from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.async_api import async_playwright
from playwright_stealth import stealth as playwright_stealth_func
import base64
import asyncio
import os
import logging
import requests
import concurrent.futures

# --- AI SDKs ---
from openai import OpenAI
import anthropic
import google.generativeai as genai

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
logging.basicConfig(level=logging.DEBUG)

# --- THE AI VISION ROUTER (UI/UX Assessment) ---
def analyze_ui_ux_with_ai(base64_image, provider_choice="openai"):
    prompt = "You are an ISTQB-certified QA engineer. Analyze this UI screenshot. Identify any alignment, contrast, usability, or UX issues. Return a brief summary of corrections."
    
    try:
        if provider_choice == "openai":
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                    ]
                }]
            )
            return response.choices[0].message.content

        elif provider_choice == "claude":
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
            response = client.messages.create(
                model="claude-3-5-sonnet-20240620",
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64_image}},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )
            return response.content[0].text

        elif provider_choice == "gemini":
            genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
            model = genai.GenerativeModel('gemini-1.5-pro')
            image_bytes = base64.b64decode(base64_image)
            image_part = {"mime_type": "image/png", "data": image_bytes}
            
            response = model.generate_content([prompt, image_part])
            return response.text

        else:
            return "ERROR: Unsupported AI Provider selected."

    except Exception as e:
        return f"Vision API Error ({provider_choice}): {str(e)}"

# --- HELPER: Safe Stealth Injection ---
async def apply_playwright_stealth(page):
    try:
        await playwright_stealth_func(page)
    except Exception as e:
        logging.warning(f"Stealth injection failed: {e}")

# --- ENGINE 1: API TESTING ---
def run_api_test(test_data):
    results = []
    status = "SUCCESS"
    steps = test_data.get('steps', [])
    
    for i, step in enumerate(steps):
        method = step.get('method', 'GET').upper()
        url = step.get('url') or step.get('value', '')
        payload = step.get('data', {})
        expected_code = int(step.get('expected_value', 200))
        
        try:
            response = requests.request(method, url, json=payload if payload else None, timeout=10)
            if response.status_code == expected_code:
                results.append(f"Step {i+1}: API {method} to {url} - PASSED (Code {response.status_code})")
            else:
                status = "FAILED"
                results.append(f"Step {i+1}: API {method} to {url} - FAILED (Expected {expected_code}, got {response.status_code})")
        except Exception as e:
            status = "FAILED"
            results.append(f"Step {i+1}: API ERROR - {str(e)}")
            
    return status, results

# --- ENGINE 2: PLAYWRIGHT (UI & UI/UX Assessment) ---
async def run_playwright_test(test_data):
    results = []
    screenshot_base64 = None
    status = "SUCCESS"
    
    browser_choice = test_data.get('browser', 'chromium').lower()
    test_type = test_data.get('test_type', 'regression').lower()
    ai_provider = test_data.get('ai_provider', 'openai').lower()
    
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
                    
                # --- NAVIGATE ---
                if action == 'navigate':
                    await page.goto(url, wait_until="domcontentloaded")
                    results.append(f"Step {i+1}: Navigated to {url}")
                    
                # --- TYPE / FILL ---
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
                    await asyncio.sleep(2)
                    
                # --- CLICK ---
                elif action == 'click':
                    selector = step.get('selector', '') 
                    loc = page.locator(selector) if selector and selector != ':root' else \
                          page.get_by_role("button", name=t_desc, exact=False).or_(
                          page.get_by_text(t_desc, exact=False)).first
                    await loc.click()
                    results.append(f"Step {i+1}: Clicked {t_desc}")

                # --- SIGN ---
                elif action == 'sign':
                    loc = page.locator("canvas").first 
                    if await loc.count() > 0:
                        box = await loc.bounding_box()
                        if box:
                            await page.mouse.move(box['x'] + 20, box['y'] + 20)
                            await page.mouse.down()
                            await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] - 20)
                            await page.mouse.move(box['x'] + box['width'] - 20, box['y'] + 20)
                            await page.mouse.up()
                            results.append(f"Step {i+1}: Signature applied to {t_desc}")
                        else:
                            raise Exception(f"Signature box for {t_desc} has no visible area.")
                    else:
                        raise Exception(f"Could not find a signature canvas for: {t_desc}")

                # --- VERIFY ---
                elif action == 'verify':
                    content = await page.content()
                    if value.lower() in content.lower():
                        results.append(f"Step {i+1}: Verified '{value}' is present.")
                    else:
                        raise Exception(f"Verification Failed: '{value}' not found.")

            # --- SCREENSHOT & UI/UX ASSESSMENT ---
            try:
                screenshot_bytes = await page.screenshot(full_page=False, timeout=8000)
                screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                
                if test_type == 'ui_ux_assessment':
                    results.append(f"--- Initiating UI/UX Assessment via {ai_provider.upper()} ---")
                    vision_insight = analyze_ui_ux_with_ai(screenshot_base64, provider_choice=ai_provider)
                    results.append(f"UI/UX Feedback: {vision_insight}")
                    
            except:
                logging.warning("Screenshot timed out.")

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
        test_type = data.get('test_type', 'regression').lower()
        
        # Branch 1: API Tests
        if test_type == 'api':
            status, logs = run_api_test(data)
            return jsonify({"status": status, "actualResults": "\n".join(logs), "screenshotBase64": None})
            
        # Branch 2: Load Tests (Simplified multi-threading)
        elif test_type == 'load':
            results_summary = []
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Running 5 concurrent users
                futures = [executor.submit(run_api_test, data) for _ in range(5)]
                for f in concurrent.futures.as_completed(futures):
                    results_summary.append(f.result()[0])
            return jsonify({"status": "SUCCESS", "actualResults": f"Load Test Complete. Thread Statuses: {results_summary}", "screenshotBase64": None})
            
        # Branch 3: Standard UI / Regression / UI_UX
        else:
            status, logs, screenshot = asyncio.run(run_playwright_test(data))
            return jsonify({"status": status, "actualResults": "\n".join(logs), "screenshotBase64": screenshot})
            
    except Exception as e:
        return jsonify({"status": "ERROR", "actualResults": str(e)}), 500

@app.route('/')
def home():
    return "Pariksha Executor is LIVE with API, Load, and UI/UX Capabilities!", 200

# --- DISCOVERY SCAN ROUTE ---
@app.route('/scan', methods=['POST'])
def scan():
    try:
        data = request.json
        url = data.get('url')
        
        async def perform_scan(target_url):
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
                context = await browser.new_context(
                    viewport={'width': 1280, 'height': 720},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await apply_playwright_stealth(page)
                
                await page.goto(target_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(5000)
                
                screenshot_bytes = await page.screenshot(full_page=False)
                debug_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                dna_map = await page.aria_snapshot()
                
                await browser.close()
                return dna_map, debug_base64

        dna_result, debug_screenshot = asyncio.run(perform_scan(url))
        
        return jsonify({
            "status": "SUCCESS",
            "url": url,
            "dna_map": dna_result,
            "debug_screenshot": debug_screenshot
        })
        
    except Exception as e:
        logging.error(f"Scan failed: {str(e)}")
        return jsonify({"status": "ERROR", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
