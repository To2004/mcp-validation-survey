"""Visit the deployed survey with a real browser so it does not hibernate.

Streamlit Community Cloud puts an app to sleep after a period without traffic, and
"traffic" means an actual app session — the browser loading the page and opening a
WebSocket back to the container. A plain HTTP request does not count: Streamlit
answers it from a static shell and returns 200 whether the app is awake, asleep, or
broken, so an HTTP-only pinger reports success while the app quietly sleeps.

This script drives headless Chromium instead. Two things about the hosted page make
a naive check fail, and both are handled here:

* the app renders inside an **iframe** (`/~/+/`), not the top-level document, so the
  survey is invisible to a selector run against the main page;
* the `<title>` is set by the hosting shell whether or not the app is running, so it
  is not evidence of anything.

Success therefore means: the survey's own text appeared inside one of the frames.
The script exits non-zero otherwise, so a failing run is visible rather than
silently green.
"""

from __future__ import annotations

import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

APP_URL = os.environ.get("APP_URL", "").strip()
# Text only the running survey renders. The sleep screen never contains it.
AWAKE_MARKER = "MCP Static Scanner Validation Survey"
WAKE_BUTTON = re.compile("get this app back up", re.IGNORECASE)

LOAD_TIMEOUT_MS = 60_000
# A cold container reinstalls its Python environment before serving.
BOOT_TIMEOUT_S = 300
POLL_INTERVAL_S = 5
# Hold the session open so the visit registers as real traffic rather than an
# instant connect/disconnect.
LINGER_MS = 15_000


def frame_texts(page) -> list[str]:
    texts = []
    for frame in page.frames:
        try:
            texts.append(frame.inner_text("body"))
        except Exception:
            # Frames detach mid-poll; a missing one is not an error.
            continue
    return texts


def click_wake_button(page) -> bool:
    """Click the 'get this app back up' button wherever it lives. True if clicked."""
    for frame in page.frames:
        try:
            button = frame.get_by_role("button", name=WAKE_BUTTON)
            if button.count():
                button.first.click()
                return True
        except Exception:
            continue
    return False


def main() -> int:
    if not APP_URL:
        print("APP_URL is not set", file=sys.stderr)
        return 2

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        opened_socket = []
        page.on("websocket", lambda ws: opened_socket.append(ws.url))

        try:
            print(f"opening {APP_URL}")
            page.goto(APP_URL, wait_until="domcontentloaded", timeout=LOAD_TIMEOUT_MS)

            woke_it = False
            deadline = time.monotonic() + BOOT_TIMEOUT_S
            while time.monotonic() < deadline:
                page.wait_for_timeout(POLL_INTERVAL_S * 1000)

                if any(AWAKE_MARKER in text for text in frame_texts(page)):
                    page.wait_for_timeout(LINGER_MS)
                    print("WOKEN" if woke_it else "ALREADY AWAKE")
                    print(f"websockets opened: {len(opened_socket)}")
                    print("app is serving the survey")
                    return 0

                if not woke_it and click_wake_button(page):
                    print("app was ASLEEP - clicked the wake button, waiting for boot")
                    woke_it = True

            print(
                f"::error::Survey did not render within {BOOT_TIMEOUT_S}s "
                f"(websockets opened: {len(opened_socket)})",
                file=sys.stderr,
            )
            for index, text in enumerate(frame_texts(page)):
                print(f"frame[{index}]: {text[:200]!r}", file=sys.stderr)
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
