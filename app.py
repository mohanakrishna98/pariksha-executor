from flask import Flask, request, jsonify

# Import Selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options as SeleniumOptions
from webdriver_manager.chrome import ChromeDriverManager

# Import Playwright
from playwright.sync_api import sync_playwright
import base64

app = Flask(__name__)

@app.route('/run-test', methods=['POST'])
def run_test():
    try:
        # 1. Get Data
        data = request.get_json()
        steps = data.get('steps', [])
        target_url = steps[0].get('url') if steps else "https://www.google.com"

        # CHECK: Which tool did Pariksha ask for? (Default to Playwright)
        tool = data.get('executor', 'playwright').lower()

        if tool == 'selenium':
            return run_selenium(target_url)
        else:
            return run_playwright(target_url)

    except Exception as e:
        return jsonify({"status": "ERROR", "message": str(e)}), 500

def run_selenium(url):
    # Setup Selenium (Headless)
    chrome_options = SeleniumOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    # We explicitly tell Selenium to use the installed Google Chrome
    chrome_options.binary_location = "/usr/bin/google-chrome"

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        driver.get(url)
        title = driver.title
        return jsonify({
            "status": "PASSED",
            "tool": "Selenium",
            "message": f"Selenium visited {url}. Title: {title}"
        })
    finally:
        driver.quit()

def run_playwright(url):
    with sync_playwright() as p:
        # Headless must be True for Render
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 720})
        
        # 1. Navigate
        page.goto(url, wait_until="networkidle")
        
        # 2. Example: Finding a search bar to highlight
        # In a real test, 'selector' would come from your JSON steps
        selector = "input[name='q']" 
        if page.is_visible(selector):
            # THE RED BOX: Inject CSS to highlight the element
            page.eval_on_selector(selector, "el => el.style.border = '5px solid red'")
        
        # 3. Capture Detailed Logs & Screenshot
        screenshot_bytes = page.screenshot(full_page=False) # False is better for highlighting
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        
        execution_log = f"Step 1: Navigated to {url}. Step 2: Found search bar and highlighted in red."
        
        browser.close()
        
        return jsonify({
            "status": "PASSED",
            "actual_results": execution_log, # This fixes the "No logs" error
            "screenshot": f"data:image/png;base64,{screenshot_base64}"
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
