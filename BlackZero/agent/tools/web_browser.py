"""
web_browser.py — Headless browser tool using Playwright.

Provides web browsing capability for agents: navigate, read pages,
fill forms, click elements, take screenshots, and extract data.

Requires: playwright (pip install playwright && playwright install chromium)
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.tools.base_tool import BaseTool

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_VIEWPORT = {"width": 1280, "height": 720}
_TIMEOUT_MS = 30_000
_MAX_TEXT_LENGTH = 5000
_MAX_LINKS = 50


class WebBrowser(BaseTool):
    """Headless Chromium browser for navigation, form filling, and data extraction."""

    @property
    def name(self) -> str:
        return "web_browser"

    @property
    def description(self) -> str:
        return "Headless web browser for navigation, form filling, and data extraction"

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._screenshots_dir = self._data_dir / "browser" / "screenshots"
        self._sessions_dir = self._data_dir / "browser" / "sessions"
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._cookies_path = self._sessions_dir / "cookies.json"

        # Lazy-initialized browser objects
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    # ---- Browser lifecycle ----

    def _ensure_browser(self) -> None:
        """Start browser + context + page if not already running."""
        if self._page is not None:
            return

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "playwright not installed. Run: pip install playwright && playwright install chromium"
            )

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent=_USER_AGENT,
            viewport=_VIEWPORT,
        )
        self._context.set_default_timeout(_TIMEOUT_MS)
        self._page = self._context.new_page()

        # Restore cookies from previous session
        self._load_cookies()

    def _load_cookies(self) -> None:
        """Load cookies from disk if available."""
        if self._cookies_path.exists():
            try:
                cookies = json.loads(self._cookies_path.read_text())
                if cookies:
                    self._context.add_cookies(cookies)
                    logger.debug("Restored %d cookies from session", len(cookies))
            except Exception as e:
                logger.warning("Failed to load cookies: %s", e)

    def _save_cookies(self) -> None:
        """Persist cookies to disk."""
        if self._context is None:
            return
        try:
            cookies = self._context.cookies()
            self._cookies_path.write_text(json.dumps(cookies, indent=2))
        except Exception as e:
            logger.warning("Failed to save cookies: %s", e)

    def _close_browser(self) -> None:
        """Shut down browser and playwright."""
        try:
            if self._page:
                self._page.close()
        except Exception:
            pass
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._pw = None

    def __del__(self) -> None:
        self._close_browser()

    # ---- Action handlers ----

    def _navigate(self, input: dict) -> dict:
        self.validate_input(input, ["url"])
        self._ensure_browser()
        resp = self._page.goto(input["url"], wait_until="domcontentloaded")
        self._save_cookies()
        return {
            "ok": True,
            "url": self._page.url,
            "title": self._page.title(),
            "status": resp.status if resp else 0,
        }

    def _read_page(self, input: dict) -> dict:
        self._ensure_browser()
        url = input.get("url")
        if url:
            self._page.goto(url, wait_until="domcontentloaded")
            self._save_cookies()

        selector = input.get("selector")
        if selector:
            el = self._page.query_selector(selector)
            text = el.inner_text() if el else ""
        else:
            text = self._page.inner_text("body")

        text = text[:_MAX_TEXT_LENGTH]

        # Extract links
        link_els = self._page.query_selector_all("a[href]")
        links = []
        for a in link_els[:_MAX_LINKS]:
            try:
                links.append({
                    "text": (a.inner_text() or "").strip()[:120],
                    "href": a.get_attribute("href") or "",
                })
            except Exception:
                continue

        return {
            "ok": True,
            "url": self._page.url,
            "title": self._page.title(),
            "text": text,
            "links": links,
        }

    def _fill_form(self, input: dict) -> dict:
        self.validate_input(input, ["fields"])
        self._ensure_browser()

        url = input.get("url")
        if url:
            self._page.goto(url, wait_until="domcontentloaded")

        fields = input["fields"]
        filled = 0
        for field in fields:
            sel = field.get("selector")
            val = field.get("value", "")
            if not sel:
                continue
            self._page.fill(sel, val)
            filled += 1

        submitted = False
        submit_sel = input.get("submit_selector")
        if submit_sel:
            self._page.click(submit_sel)
            self._page.wait_for_load_state("domcontentloaded")
            submitted = True

        self._save_cookies()
        return {
            "ok": True,
            "fields_filled": filled,
            "submitted": submitted,
            "result_url": self._page.url,
            "result_title": self._page.title(),
        }

    def _click(self, input: dict) -> dict:
        self.validate_input(input, ["selector"])
        self._ensure_browser()
        selector = input["selector"]
        wait_after = float(input.get("wait_after", 2.0))

        self._page.click(selector)
        if wait_after > 0:
            time.sleep(wait_after)

        self._save_cookies()
        return {
            "ok": True,
            "clicked": selector,
            "result_url": self._page.url,
            "result_title": self._page.title(),
        }

    def _screenshot(self, input: dict) -> dict:
        self._ensure_browser()
        url = input.get("url")
        if url:
            self._page.goto(url, wait_until="domcontentloaded")
            self._save_cookies()

        full_page = input.get("full_page", True)
        filename = input.get("filename")
        if not filename:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{ts}"
        if not filename.endswith(".png"):
            filename += ".png"

        path = self._screenshots_dir / filename
        self._page.screenshot(path=str(path), full_page=full_page)
        return {
            "ok": True,
            "path": str(path),
            "url": self._page.url,
        }

    def _extract(self, input: dict) -> dict:
        self.validate_input(input, ["selectors"])
        self._ensure_browser()

        url = input.get("url")
        if url:
            self._page.goto(url, wait_until="domcontentloaded")
            self._save_cookies()

        selectors = input["selectors"]
        data = {}
        for field_name, css in selectors.items():
            el = self._page.query_selector(css)
            data[field_name] = el.inner_text().strip() if el else None

        return {"ok": True, "data": data}

    def _signup(self, input: dict) -> dict:
        self.validate_input(input, ["url", "fields", "submit_selector"])
        self._ensure_browser()

        # Navigate
        self._page.goto(input["url"], wait_until="domcontentloaded")

        # Fill fields
        for field in input["fields"]:
            sel = field.get("selector")
            val = field.get("value", "")
            if sel:
                self._page.fill(sel, val)

        # Submit
        self._page.click(input["submit_selector"])
        self._page.wait_for_load_state("domcontentloaded")
        self._save_cookies()

        # Check confirmation
        confirmation_text = input.get("confirmation_text")
        confirmation_found = False
        if confirmation_text:
            try:
                body_text = self._page.inner_text("body")
                confirmation_found = confirmation_text.lower() in body_text.lower()
            except Exception:
                pass

        return {
            "ok": True,
            "signed_up": True,
            "confirmation_found": confirmation_found,
            "result_url": self._page.url,
            "result_title": self._page.title(),
        }

    def _close(self, _input: dict) -> dict:
        self._save_cookies()
        self._close_browser()
        return {"ok": True, "closed": True}

    # ---- Main dispatch ----

    _ACTIONS = {
        "navigate": "_navigate",
        "read_page": "_read_page",
        "fill_form": "_fill_form",
        "click": "_click",
        "screenshot": "_screenshot",
        "extract": "_extract",
        "signup": "_signup",
        "close": "_close",
    }

    def run(self, input: dict[str, Any]) -> dict[str, Any]:
        action = input.get("action")
        if not action:
            return {"ok": False, "error": "Missing 'action' key. Valid actions: " + ", ".join(self._ACTIONS)}

        handler_name = self._ACTIONS.get(action)
        if not handler_name:
            return {"ok": False, "error": f"Unknown action '{action}'. Valid: {', '.join(self._ACTIONS)}"}

        try:
            handler = getattr(self, handler_name)
            return handler(input)
        except RuntimeError as e:
            # Catches playwright-not-installed and similar
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.exception("web_browser.%s failed", action)
            return {"ok": False, "error": str(e)}
