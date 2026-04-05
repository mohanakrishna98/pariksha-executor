from flask import Flask, request, jsonify
from playwright.async_api import async_playwright
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
import base64
import asyncio
import os
import time

app = Flask(__name__)

# --- PLAYWRIGHT ENGINE (With Combobox Fix) ---
async def run_playwright_test(test_data):
    results = []
    screenshot_base64 = None
    status = "SUCCESS"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 720})
        page = await context.new_page()
        
        try:
            steps = test_data.get('steps') or test_data.get('testCase', [])
            for i, step in enumerate(steps):
                action = step.get('action', '').lower()
                target_name = step.get('target_description', '')
                selector = step.get('selector', '')
                value = step.get('value') or step.get('data', '')

                if action == 'navigate':
                    await page.goto(value, wait_until="networkidle")
                    results.append(f"Step {i+1}: Navigated to {value}")

                elif action in ['type', 'fill']:
                    # Priority: 1. Explicit Selector | 2. Combobox/Textbox Role | 3. Label/Placeholder
                    if selector:
                        locator = page.locator(selector)
                    else:
                        combobox = page.get_by_role("combobox", name=target_name, exact=False)
                        textbox = page.get_by_role("textbox", name=target_name, exact=False)
                        if await combobox.count() > 0:
                            locator = combobox.first
                        elif await textbox.count() > 0:
                            locator = textbox.first
                        else:
                            locator = page.get_by_label(target_name).or_(page.get_by_placeholder(target_name)).first
                    
                    await locator.fill(value)
                    results.append(f"Step {i+1}: Typed '{value}' into {target_name}")

                elif action == 'click':
                    locator = page.locator(selector) if selector else page.get_by_role("button", name=target_name).or_(page.get_by_text(target_name)).first
                    await locator.click()
                    results.append(f"Step {i+1}: Clicked {target_name}")

            screenshot_bytes = await page.screenshot(full_page=True)
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

        except Exception as e:
            status = "FAILED"
            results.append(f"Step FAILED: {str(e)}")
        finally:
            await browser.close()
            
    return status, results, screenshot_base64

# --- SELENIUM ENGINE ---
def run_selenium_test(test_data):
    results = []
    screenshot_base64 = None
    status = "SUCCESS"
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        steps = test_data.get('steps') or test_data.get('testCase', [])
        for i, step in enumerate(steps):
            action = step.get('action', '').lower()
            value = step.get('value') or step.get('data', '')
            
            if action == 'navigate':
                driver.get(value)
                results.append(f"Step {i+1}: (Selenium) Navigated to {value}")
            # Add additional Selenium action logic (find_element) here as needed
            
        screenshot_bytes = driver.get_screenshot_as_png()
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        
    except Exception as e:
        status = "FAILED"
        results.append(f"Selenium FAILED: {str(e)}")
    finally:
        driver.quit()
        
    return status, results, screenshot_base64

# --- THE RELAY ROUTE ---
@app.route('/run-test', methods=['POST'])
async def run_test():
    data = request.json
    executor_type = data.get('executor_type', 'playwright').lower()
    
    if executor_type == 'selenium':
        status, logs, screenshot = run_selenium_test(data)
    else:
        status, logs, screenshot = await run_playwright_test(data)
    
    return jsonify({
        "status": status,
        "actualResults": "\n".join(logs),
        "screenshotBase64": screenshot
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
