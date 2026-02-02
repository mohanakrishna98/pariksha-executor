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
        
        # Set a standard desktop screen size
        page.set_viewport_size({"width": 1280, "height": 720})
        
        # Visit the site
        page.goto(url, wait_until="networkidle")
        
        # 1. CAPTURE THE SCREENSHOT
        # We convert the image to a Base64 string so it can travel via JSON
        screenshot_bytes = page.screenshot(full_page=True)
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        
        title = page.title()
        browser.close()
        
        return jsonify({
            "status": "PASSED",
            "message": f"Pariksha successfully visited {url}",
            "page_title": title,
            "screenshot": f"data:image/png;base64,{screenshot_base64}"
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
