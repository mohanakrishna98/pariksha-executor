from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options as SeleniumOptions
from webdriver_manager.chrome import ChromeDriverManager
from playwright.sync_api import sync_playwright
import base64

app = Flask(__name__)

@app.route('/run-test', methods=['POST'])
def run_test():
    try:
        # 1. Get the JSON data from the request
        data = request.get_json()
        if not data:
            return jsonify({"status": "ERROR", "message": "No JSON data received"}), 400

        # 2. Determine which tool to use
        tool = data.get('executor', 'playwright').lower()

        # 3. Call the appropriate function and PASS the data variable
        if tool == 'selenium':
            # Selenium currently only handles a simple URL visit in this MVP
            steps = data.get('steps', [])
            target_url = steps[0].get('url') if steps else "https://www.google.com"
            return run_selenium(target_url)
        else:
            # Playwright handles the full execution loop
            return run_playwright(data)

    except Exception as e:
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
            "actual_results": f"Selenium visited {url}. Title: {title}"
        })
    finally:
        driver.quit()

def run_playwright(data):
    # Now 'data' is correctly received as an argument
    steps = data.get('steps', [])
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 720})
        
        logs = []
        screenshot_base64 = None
        
        for i, step in enumerate(steps):
            action = step.get('action')
            desc = step.get('target_description', 'element')
            step_url = step.get('url')
            step_data = step.get('data')
            
            try:
                if action == 'navigate':
                    page.goto(step_url, wait_until="networkidle")
                    logs.append(f"✅ Step {i+1}: Navigated to {step_url}")
                
                elif action == 'type':
                    # Flexible locator: tries placeholder, then label, then text
                    page.get_by_placeholder(desc, exact=False).or_(page.get_by_label(desc, exact=False)).fill(step_data)
                    logs.append(f"✅ Step {i+1}: Typed '{step_data}' into {desc}")
                
                elif action == 'click':
                    page.get_by_role("button", name=desc, exact=False).or_(page.get_by_text(desc, exact=False)).click()
                    logs.append(f"✅ Step {i+1}: Clicked {desc}")

                # Take a screenshot after the final step
                if i == len(steps) - 1:
                    screenshot_bytes = page.screenshot(full_page=False)
                    screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

            except Exception as e:
                logs.append(f"❌ Step {i+1} FAILED: {str(e)}")
                # Take error screenshot
                screenshot_bytes = page.screenshot(full_page=False)
                screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                break 

        browser.close()
        
        return jsonify({
            "status": "PASSED" if "❌" not in "".join(logs) else "FAILED",
            "actual_results": "\n".join(logs),
            "screenshotBase64": screenshot_base64 if screenshot_base64 else None
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
