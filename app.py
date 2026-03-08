from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options as SeleniumOptions
from webdriver_manager.chrome import ChromeDriverManager
from playwright.sync_api import sync_playwright
import base64

app = Flask(__name__)

# HYBRID LOCATOR STRATEGY: Combines Option A (Precision) and Option B (Self-Healing)
def find_element(page, selector, desc):
    """
    Attempts to find an element using multiple strategies to increase test resilience.
    """
    # Strategy 1: Attempt the direct CSS selector (Option A)
    if selector:
        loc = page.locator(selector)
        if loc.count() > 0:
            return loc

    # Strategy 2: Attempt to find by Test ID or ARIA labels (Option B)
    loc = page.locator(f"[data-testid='{desc}']").or_(
          page.get_by_placeholder(desc, exact=False)
    ).or_(
          page.get_by_label(desc, exact=False)
    )
    if loc.count() > 0:
        return loc

    # Strategy 3: Semantic Roles (Button/Link) fallback
    loc = page.get_by_role("button", name=desc, exact=False).or_(
          page.get_by_role("link", name=desc, exact=False)
    )
    if loc.count() > 0:
        return loc

    # Strategy 4: Final Fuzzy Text Match
    return page.get_by_text(desc, exact=False)

@app.route('/run-test', methods=['POST'])
def run_test():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "ERROR", "message": "No JSON data received"}), 400

        print(f"DEBUG: Received request. Payload: {data}")

        tool = data.get('executor', 'playwright').lower()

        if tool == 'selenium':
            steps = data.get('steps') or data.get('testCase', {}).get('steps', [])
            target_url = steps[0].get('url') if steps else "https://www.google.com"
            return run_selenium(target_url)
        else:
            return run_playwright(data)

    except Exception as e:
        print(f"DEBUG ERROR: {str(e)}")
        return jsonify({"status": "ERROR", "message": str(e)}), 500

def run_selenium(url):
    chrome_options = SeleniumOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.binary_location = "/usr/bin/google-chrome"

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        driver.get(url)
        title = driver.title
        return jsonify({
            "status": "PASSED",
            "tool": "Selenium",
            "actualResults": f"Selenium visited {url}. Title: {title}" 
        })
    finally:
        driver.quit()

def run_playwright(data):
    steps = data.get('steps') or data.get('testCase', {}).get('steps', [])
    
    if not steps:
         return jsonify({"status": "FAILED", "actualResults": "No steps found in the payload."})

    with sync_playwright() as p:
        # Launching the headless engine on Render
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 720})
        
        logs = []
        screenshot_raw = None
        
        for i, step in enumerate(steps):
            action = step.get('action')
            desc = step.get('target_description', step.get('value', 'element'))
            step_url = step.get('url')
            step_data = step.get('data', step.get('value', ''))
            # Priority on provided CSS selector
            provided_selector = step.get('selector') 
            
            try:
                if action == 'navigate':
                    page.goto(step_url, wait_until="networkidle", timeout=30000)
                    logs.append(f"✅ Step {i+1}: Navigated to {step_url}")
                
                elif action in ['type', 'fill']:
                    # Use the Hybrid Strategy to find the input
                    target = find_element(page, provided_selector, desc)
                    target.fill(step_data)
                    logs.append(f"✅ Step {i+1}: Typed '{step_data}' into '{desc}'")
                
                elif action == 'click':
                    # Use the Hybrid Strategy to find the button/link
                    target = find_element(page, provided_selector, desc)
                    target.click()
                    logs.append(f"✅ Step {i+1}: Clicked '{desc}'")

                elif action == 'waitFor':
                    timeout = int(step.get('waitTime', 5)) * 1000
                    page.wait_for_timeout(timeout)
                    logs.append(f"✅ Step {i+1}: Waited for {timeout/1000}s")

                # Capture final state screenshot
                if i == len(steps) - 1:
                    screenshot_bytes = page.screenshot(full_page=False)
                    screenshot_raw = base64.b64encode(screenshot_bytes).decode('utf-8')

            except Exception as e:
                logs.append(f"❌ Step {i+1} FAILED: {str(e)}")
                screenshot_bytes = page.screenshot(full_page=False)
                screenshot_raw = base64.b64encode(screenshot_bytes).decode('utf-8')
                break 

        browser.close()
        
        return jsonify({
            "status": "PASSED" if "❌" not in "".join(logs) else "FAILED",
            "actualResults": "\n".join(logs), 
            "screenshotBase64": screenshot_raw
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
