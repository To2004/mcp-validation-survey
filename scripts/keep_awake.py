"""Visit the deployed survey with a real browser so it does not hibernate.

Streamlit Community Cloud puts an app to sleep after a period without traffic, and
"traffic" means an actual app session — the browser loading the page and opening a
WebSocket back to the container. A plain HTTP request does not count: Streamlit
answers it from a static shell and returns 200 whether the app is awake, asleep, or
broken. An HTTP-only pinger therefore reports success while the app quietly sleeps.

This script drives headless Chromium instead. It loads the app, clicks the wake
button if it finds the sleep screen, and only reports success once the survey itself
has rendered. It exits non-zero if it cannot get there, so a failing run is visible
rather than silently green.
"""

from __future__ import annotations

import os
import re
import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

APP_URL = os.environ.get("APP_URL", "").strip()
# Something only the running app renders. The sleep screen never contains it.
AWAKE_MARKER = "MCP Static Scanner Validation Survey"
WAKE_BUTTON = re.compile("get this app back up", re.IGNORECASE)

LOAD_TIMEOUT_MS = 60_000
# A cold container reinstalls its Python environment before serving.
BOOT_TIMEOUT_MS = 240_000


def main() -> int:
    if not APP_URL:
        print("APP_URL is not set", file=sys.stderr)
        return 2

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            print(f"opening {APP_URL}")
            page.goto(APP_URL, wait_until="domcontentloaded", timeout=LOAD_TIMEOUT_MS)

            # Give the client-side app a moment to render either screen.
            page.wait_for_timeout(5_000)

            wake_button = page.get_by_role("button", name=WAKE_BUTTON)
            was_asleep = wake_button.count() > 0
            if was_asleep:
                print("app was ASLEEP - clicking the wake button")
                wake_button.first.click()

            print("waiting for the survey to render")
            page.wait_for_selector(f"text={AWAKE_MARKER}", timeout=BOOT_TIMEOUT_MS)

            # Hold the session open briefly so the visit registers as real traffic
            # rather than an instant connect/disconnect.
            page.wait_for_timeout(10_000)

            print("WOKEN" if was_asleep else "ALREADY AWAKE")
            print("app is serving the survey")
            return 0
        except PlaywrightTimeout as exc:
            print(f"::error::App did not render within the timeout: {exc}", file=sys.stderr)
            print(page.content()[:1500], file=sys.stderr)
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
