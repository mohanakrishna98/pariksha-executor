from quart import Quart, request, jsonify
from quart_cors import cors
from playwright.async_api import async_playwright
from playwright_stealth import stealth as playwright_stealth_func
import base64
import asyncio
import os
import logging
import httpx
import concurrent.futures
from functools import wraps

# --- AI SDKs ---
from openai import AsyncOpenAI
import anthropic
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------------
app = Quart(__name__)
app = cors(app, allow_origin="*")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config & Startup Validation
# ---------------------------------------------------------------------------
AI_MODELS = {
    "openai":  os.environ.get("OPENAI_MODEL",  "gpt-4o"),
    "claude":  os.environ.get("CLAUDE_MODEL",   "claude-3-5-sonnet-20241022"),
    "gemini":  os.environ.get("GEMINI_MODEL",   "gemini-1.5-pro"),
}

EXECUTOR_SECRET = os.environ.get("EXECUTOR_SECRET")

def _check_env_keys():
    """Warn at startup if any AI provider keys are missing."""
    keys = {
        "OPENAI_API_KEY":    "OpenAI",
        "ANTHROPIC_API_KEY": "Claude (Anthropic)",
        "GEMINI_API_KEY":    "Gemini (Google)",
    }
    for env_var, label in keys.items():
        if not os.environ.get(env_var):
            logger.warning("Missing API key for %s (%s). That provider will be unavailable.", label, env_var)

_check_env_keys()

# ---------------------------------------------------------------------------
# Auth Middleware
# ---------------------------------------------------------------------------
def require_token(f):
    """
    Protect endpoints with a simple bearer / header token.
    Set EXECUTOR_SECRET env var to enable. If unset, auth is skipped
    (useful for local dev — always set it in production).
    """
    @wraps(f)
    async def decorated(*args, **kwargs):
        if EXECUTOR_SECRET:
            token = request.headers.get("X-API-Key", "")
            if token != EXECUTOR_SECRET:
                return jsonify({"error": "Unauthorized"}), 401
        return await f(*args, **kwargs)
    return decorated

# ---------------------------------------------------------------------------
# AI Vision Router  (UI/UX Assessment)
# ---------------------------------------------------------------------------
async def analyze_ui_ux_with_ai(base64_image: str, provider_choice: str = "openai") -> str:
    """
    Send a UI screenshot to the chosen AI provider and return UX feedback.
    All calls are async-native to avoid blocking the event loop.
    """
    prompt = (
        "You are an ISTQB-certified QA engineer and senior UX reviewer. "
        "Analyse this UI screenshot. Identify alignment, contrast, usability, "
        "accessibility (WCAG), and UX issues. Return a concise, prioritised list of corrections."
    )

    try:
        # --- OpenAI ---
        if provider_choice == "openai":
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                return "ERROR: OPENAI_API_KEY is not set."
            client = AsyncOpenAI(api_key=api_key)
            response = await client.chat.completions.create(
                model=AI_MODELS["openai"],
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                    ]
                }],
                max_tokens=600,
            )
            return response.choices[0].message.content

        # --- Claude ---
        elif provider_choice == "claude":
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                return "ERROR: ANTHROPIC_API_KEY is not set."
            # Use the sync client in a thread to avoid blocking (anthropic SDK lacks full async)
            client = anthropic.Anthropic(api_key=api_key)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.messages.create(
                    model=AI_MODELS["claude"],
                    max_tokens=600,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64_image}},
                            {"type": "text", "text": prompt}
                        ]
                    }]
                )
            )
            return response.content[0].text

        # --- Gemini ---
        elif provider_choice == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                return "ERROR: GEMINI_API_KEY is not set."
            client = genai.Client(api_key=api_key)
            image_bytes = base64.b64decode(base64_image)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model=AI_MODELS["gemini"],
                    contents=[prompt, types.Part.from_bytes(data=image_bytes, mime_type="image/png")]
                )
            )
            return response.text

        else:
            return f"ERROR: Unsupported AI provider '{provider_choice}'. Choose openai, claude, or gemini."

    except Exception as e:
        logger.exception("Vision API error with provider '%s'", provider_choice)
        return f"Vision API Error ({provider_choice}): {str(e)}"


# ---------------------------------------------------------------------------
# Helper: Stealth Injection
# ---------------------------------------------------------------------------
async def apply_playwright_stealth(page):
    try:
        await playwright_stealth_func(page)
    except Exception as e:
        logger.warning("Stealth injection failed (non-fatal): %s", e)


# ---------------------------------------------------------------------------
# Helper: Shared Browser Context Factory
# ---------------------------------------------------------------------------
async def create_browser_context(playwright_instance, browser_choice: str = "chromium"):
    browser_map = {
        "chromium": playwright_instance.chromium,
        "firefox":  playwright_instance.firefox,
        "webkit":   playwright_instance.webkit,
    }
    engine = browser_map.get(browser_choice, playwright_instance.chromium)
    browser = await engine.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"]
    )
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 720},
    )
    return browser, context


# ---------------------------------------------------------------------------
# Engine 1: API Testing  (async, uses httpx)
# ---------------------------------------------------------------------------
async def run_api_test(test_data: dict) -> tuple[str, list[str]]:
    results = []
    status = "SUCCESS"
    steps = test_data.get("steps", [])

    async with httpx.AsyncClient(timeout=10) as client:
        for i, step in enumerate(steps):
            method        = step.get("method", "GET").upper()
            url           = step.get("url") or step.get("value", "")
            payload       = step.get("data") or None
            expected_code = int(step.get("expected_value", 200))

            if not url:
                results.append(f"Step {i+1}: SKIPPED — no URL provided")
                continue

            try:
                response = await client.request(method, url, json=payload)
                if response.status_code == expected_code:
                    results.append(
                        f"Step {i+1}: {method} {url} — PASSED (HTTP {response.status_code})"
                    )
                else:
                    status = "FAILED"
                    results.append(
                        f"Step {i+1}: {method} {url} — FAILED "
                        f"(expected {expected_code}, got {response.status_code})"
                    )
            except Exception as e:
                status = "FAILED"
                results.append(f"Step {i+1}: {method} {url} — ERROR: {e}")

    return status, results


# ---------------------------------------------------------------------------
# Engine 2: Playwright  (UI Regression / UI-UX Assessment)
# ---------------------------------------------------------------------------
async def run_playwright_test(test_data: dict) -> tuple[str, list[str], str | None]:
    results         = []
    screenshot_b64  = None
    status          = "SUCCESS"

    browser_choice  = test_data.get("browser",      "chromium").lower()
    test_type       = test_data.get("test_type",     "regression").lower()
    ai_provider     = test_data.get("ai_provider",   "openai").lower()

    # Support nested testCase payload or flat payload
    test_payload = (
        test_data["testCase"]
        if isinstance(test_data.get("testCase"), dict)
        else test_data
    )
    steps = test_payload.get("steps", [])

    async with async_playwright() as p:
        browser, context = await create_browser_context(p, browser_choice)
        page = await context.new_page()
        await apply_playwright_stealth(page)

        try:
            for i, step in enumerate(steps):
                action  = step.get("action", "").lower()
                t_desc  = step.get("target_description", "Element")
                value   = step.get("data") or step.get("expected_value") or step.get("value", "")
                url     = step.get("url") or value

                # --- NAVIGATE ---
                if action == "navigate":
                    await page.goto(url, wait_until="domcontentloaded")
                    await page.wait_for_load_state("networkidle")
                    results.append(f"Step {i+1}: Navigated to {url}")

                # --- TYPE / FILL ---
                elif action in ("type", "fill"):
                    clean_name = t_desc.lower().replace(" box", "").strip()
                    loc = (
                        page.get_by_role("searchbox", name=clean_name, exact=False)
                        .or_(page.get_by_role("textbox",   name=clean_name, exact=False))
                        .or_(page.get_by_role("combobox",  name=clean_name, exact=False))
                        .first
                    )
                    if await loc.count() == 0:
                        loc = page.locator(
                            f"input[name*='{clean_name}'], input[id*='{clean_name}']"
                        ).first

                    await loc.fill(value)
                    await page.keyboard.press("Enter")
                    # Wait for network to settle instead of arbitrary sleep
                    await page.wait_for_load_state("networkidle")
                    results.append(f"Step {i+1}: Typed '{value}' into {t_desc}")

                # --- CLICK ---
                elif action == "click":
                    selector = step.get("selector", "")
                    if selector and selector != ":root":
                        loc = page.locator(selector)
                    else:
                        loc = (
                            page.get_by_role("button", name=t_desc, exact=False)
                            .or_(page.get_by_text(t_desc, exact=False))
                            .first
                        )
                    await loc.click()
                    await page.wait_for_load_state("networkidle")
                    results.append(f"Step {i+1}: Clicked '{t_desc}'")

                # --- SIGN (canvas signature) ---
                elif action == "sign":
                    canvas = page.locator("canvas").first
                    if await canvas.count() > 0:
                        box = await canvas.bounding_box()
                        if box:
                            cx, cy, w, h = box["x"], box["y"], box["width"], box["height"]
                            await page.mouse.move(cx + 20,       cy + 20)
                            await page.mouse.down()
                            await page.mouse.move(cx + w / 2,    cy + h - 20)
                            await page.mouse.move(cx + w - 20,   cy + 20)
                            await page.mouse.up()
                            results.append(f"Step {i+1}: Signature applied to {t_desc}")
                        else:
                            raise RuntimeError(f"Signature canvas for '{t_desc}' has no visible bounding box.")
                    else:
                        raise RuntimeError(f"No <canvas> element found for signature: '{t_desc}'")

                # --- VERIFY ---
                elif action == "verify":
                    content = await page.content()
                    if value.lower() in content.lower():
                        results.append(f"Step {i+1}: Verified '{value}' is present.")
                    else:
                        raise AssertionError(f"Verification FAILED: '{value}' not found on page.")

                else:
                    logger.warning("Step %d: Unknown action '%s' — skipped.", i + 1, action)
                    results.append(f"Step {i+1}: Unknown action '{action}' — skipped.")

            # --- SCREENSHOT ---
            try:
                screenshot_bytes = await page.screenshot(full_page=False, timeout=8000)
                screenshot_b64   = base64.b64encode(screenshot_bytes).decode("utf-8")
            except Exception as e:
                logger.warning("Screenshot failed (non-fatal): %s", e)

            # --- UI/UX ASSESSMENT (optional) ---
            if test_type == "ui_ux_assessment" and screenshot_b64:
                results.append(f"--- Initiating UI/UX Assessment via {ai_provider.upper()} ---")
                vision_insight = await analyze_ui_ux_with_ai(screenshot_b64, provider_choice=ai_provider)
                results.append(f"UI/UX Feedback:\n{vision_insight}")

        except Exception as e:
            status = "FAILED"
            results.append(f"ERROR: {e}")
            logger.exception("Playwright test failed")
        finally:
            await browser.close()

    return status, results, screenshot_b64


# ---------------------------------------------------------------------------
# Engine 3: Load Testing
# ---------------------------------------------------------------------------
async def run_load_test(test_data: dict, virtual_users: int = 5) -> tuple[str, list[str]]:
    """
    Fire `virtual_users` concurrent API test coroutines and collect results.
    Uses asyncio.gather instead of ThreadPoolExecutor so we stay non-blocking.
    """
    tasks    = [run_api_test(test_data) for _ in range(virtual_users)]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    statuses = []
    for outcome in outcomes:
        if isinstance(outcome, Exception):
            statuses.append("ERROR")
        else:
            statuses.append(outcome[0])   # "SUCCESS" or "FAILED"

    overall = "SUCCESS" if all(s == "SUCCESS" for s in statuses) else "FAILED"
    summary = [
        f"Load Test — {virtual_users} Virtual Users",
        f"Results per user: {statuses}",
        f"Overall: {overall}",
    ]
    return overall, summary


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/")
async def home():
    return "Pariksha Executor is LIVE — API, Load, UI, and UI/UX capabilities ready.", 200


@app.route("/run-test", methods=["POST"])
@require_token
async def run_test():
    try:
        data      = await request.get_json(force=True)
        test_type = data.get("test_type", "regression").lower()

        if test_type == "api":
            status, logs = await run_api_test(data)
            return jsonify({"status": status, "actualResults": "\n".join(logs), "screenshotBase64": None})

        elif test_type == "load":
            virtual_users = int(data.get("virtual_users", 5))
            status, logs  = await run_load_test(data, virtual_users=virtual_users)
            return jsonify({"status": status, "actualResults": "\n".join(logs), "screenshotBase64": None})

        else:
            # regression / ui_ux_assessment / any UI test
            status, logs, screenshot = await run_playwright_test(data)
            return jsonify({"status": status, "actualResults": "\n".join(logs), "screenshotBase64": screenshot})

    except Exception as e:
        logger.exception("Unhandled error in /run-test")
        return jsonify({"status": "ERROR", "actualResults": str(e)}), 500


@app.route("/scan", methods=["POST"])
@require_token
async def scan():
    try:
        data = await request.get_json(force=True)
        url  = data.get("url")
        if not url:
            return jsonify({"status": "ERROR", "message": "'url' field is required"}), 400

        async with async_playwright() as p:
            browser, context = await create_browser_context(p, "chromium")
            page = await context.new_page()
            await apply_playwright_stealth(page)

            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle")

            screenshot_bytes = await page.screenshot(full_page=False)
            debug_b64        = base64.b64encode(screenshot_bytes).decode("utf-8")
            dna_map          = await page.aria_snapshot()

            await browser.close()

        return jsonify({
            "status":           "SUCCESS",
            "url":              url,
            "dna_map":          dna_map,
            "debug_screenshot": debug_b64,
        })

    except Exception as e:
        logger.exception("Scan failed for URL: %s", data.get("url", "unknown"))
        return jsonify({"status": "ERROR", "message": str(e)}), 500


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
