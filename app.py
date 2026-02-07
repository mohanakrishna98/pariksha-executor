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
        # 1. Capture incoming JSON from BuildAI
        data = request.get_json()
        if not data:
            return jsonify({"status": "ERROR", "message": "No JSON data received"}), 400

        # 2. Check for the executor tool (Default to Playwright)
        tool = data.get('executor', 'playwright').lower()

        if tool == 'selenium':
            steps = data.get('steps', [])
            target_url = steps[0].get('url') if steps else "https://www.google.com"
            return run_selenium(target_url)
        else:
            # PASS 'data' as an argument to fix the 'not defined' error
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
            "actualResults": f"Selenium visited {url}. Title: {title}" # camelCase for app
        })
    finally:
        driver.quit()

def run_playwright(data):
    # Retrieve steps from the passed 'data' variable
    steps = data.get('steps', [])
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 720})
        
        logs = []
        screenshot_raw = None
        
        for i, step in enumerate(steps):
            action = step.get('action')
            desc = step.get('target_description', 'element')
            step_url = step.get('url')
            step_data = step.get('data', '')
            
            try:
                # Add a small wait to ensure page stability
                if action == 'navigate':
                    page.goto(step_url, wait_until="networkidle")
                    logs.append(f"✅ Step {i+1}: Navigated to {step_url}")
                
                elif action == 'type':
                    # Priority 1: data-testid
                    # Priority 2: placeholder/label/text fallback
                    selector = page.locator(f"[data-testid='{desc}']").or_(
                        page.get_by_placeholder(desc, exact=False)
                    ).or_(
                        page.get_by_label(desc, exact=False)
                    )
                    selector.fill(step_data)
                    logs.append(f"✅ Step {i+1}: Typed into '{desc}'")
                
                elif action == 'click':
                    # Priority 1: data-testid
                    # Priority 2: role/text fallback
                    selector = page.locator(f"[data-testid='{desc}']").or_(
                        page.get_by_role("button", name=desc, exact=False)
                    ).or_(
                        page.get_by_text(desc, exact=False)
                    )
                    selector.click()
                    logs.append(f"✅ Step {i+1}: Clicked '{desc}'")

                # Capture raw Base64 screenshot on final step or error
                if i == len(steps) - 1:
                    screenshot_bytes = page.screenshot(full_page=False)
                    screenshot_raw = base64.b64encode(screenshot_bytes).decode('utf-8')

            except Exception as e:
                logs.append(f"❌ Step {i+1} FAILED: {str(e)}")
                # Error snapshot
                screenshot_bytes = page.screenshot(full_page=False)
                screenshot_raw = base64.b64encode(screenshot_bytes).decode('utf-8')
                break 

        browser.close()
        
        # Return keys matching your app's frontend mapping
        return jsonify({
            "status": "PASSED" if "❌" not in "".join(logs) else "FAILED",
            "actualResults": "\n".join(logs),
            "screenshotBase64": screenshot_raw
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
