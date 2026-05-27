"""Playwright-based action executor for the agent loop."""

from __future__ import annotations

import logging
import re
from typing import Any

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    sync_playwright,
    TimeoutError as PwTimeout,
)

from task1_agent.agent.dom_serialize import compress_a11y
from task1_agent.agent.loop import StepResult
from task1_agent.agent.recovery import FailureType, classify_failure
from task1_agent.agent.verify import VerifyResult, verify_step

logger = logging.getLogger(__name__)

_LAUNCH_ARGS = ["--disable-dev-shm-usage", "--no-sandbox"]
_DEFAULT_TIMEOUT = 20000


class PlaywrightExecutor:
    """Manages a single browser instance across multiple steps."""

    def __init__(self, *, headless: bool = True, timeout_ms: int = _DEFAULT_TIMEOUT):
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def start(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            args=_LAUNCH_ARGS,
            headless=self._headless,
        )
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self._timeout_ms)

    def close(self) -> None:
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

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Executor not started")
        return self._page

    def __call__(self, action: str, context: dict) -> StepResult:
        """Execute an action and return a StepResult with verification."""
        step_index = context.get("step", 0)
        task = context.get("task", "")
        start_url = context.get("start_url", "")
        strategy = context.get("strategy")
        planned_action = context.get("planned_action")

        try:
            if action.startswith("recovery:"):
                return self._do_recovery(step_index, task, start_url, strategy or action)
            if planned_action:
                return self._do_planned_action(step_index, task, start_url, planned_action)
            return self._do_navigate(step_index, task, start_url)
        except PwTimeout as exc:
            return StepResult(
                step_index=step_index,
                action=action,
                url=self._safe_url(),
                error=f"Timeout: {exc}",
                verify=VerifyResult(passed=False, reason=f"Timeout: {exc}"),
                failure_type=FailureType.TIMEOUT,
            )
        except Exception as exc:
            ft = classify_failure(str(exc))
            return StepResult(
                step_index=step_index,
                action=action,
                url=self._safe_url(),
                error=str(exc),
                verify=VerifyResult(passed=False, reason=str(exc)),
                failure_type=ft,
            )

    def _safe_url(self) -> str:
        try:
            return self.page.url if self._page else ""
        except Exception:
            return ""

    def _do_navigate(self, step_index: int, task: str, start_url: str) -> StepResult:
        """Navigate to start_url and observe page state."""
        page = self.page
        if step_index == 0 and start_url:
            page.goto(start_url, wait_until="domcontentloaded", timeout=self._timeout_ms)

        page.wait_for_timeout(500)
        return self._observe(step_index, f"navigate:{start_url}", task, start_url)

    def _do_planned_action(
        self, step_index: int, task: str, start_url: str, planned_action: dict
    ) -> StepResult:
        """Execute an LLM-planned action."""
        page = self.page
        action_type = planned_action.get("action", "none")
        selector = planned_action.get("selector", "")
        value = planned_action.get("value", "")

        action_desc = f"{action_type}:{selector or value}"

        if action_type == "click":
            self._do_click(page, selector)
        elif action_type == "type":
            self._do_type(page, selector, value)
        elif action_type == "scroll":
            page.evaluate("window.scrollBy(0, 400)")
        elif action_type == "press_key":
            page.keyboard.press(value or "Enter")
        elif action_type == "navigate":
            if value:
                page.goto(value, wait_until="domcontentloaded", timeout=self._timeout_ms)
        elif action_type == "none":
            pass
        else:
            logger.warning("Unknown action type: %s", action_type)

        page.wait_for_timeout(800)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except PwTimeout:
            pass

        return self._observe(step_index, action_desc, task, start_url)

    def _do_click(self, page: Page, selector: str) -> None:
        """Click an element using multiple strategies."""
        if not selector:
            return

        # Strategy 1: try exact text match with getByText
        try:
            locator = page.get_by_text(selector, exact=False)
            if locator.count() > 0:
                locator.first.click(timeout=5000)
                return
        except Exception:
            pass

        # Strategy 2: try role-based (button, link)
        for role in ["link", "button"]:
            try:
                locator = page.get_by_role(role, name=re.compile(re.escape(selector), re.I))
                if locator.count() > 0:
                    locator.first.click(timeout=5000)
                    return
            except Exception:
                pass

        # Strategy 3: CSS selector
        try:
            page.click(selector, timeout=5000)
            return
        except Exception:
            pass

        # Strategy 4: label / placeholder
        try:
            locator = page.get_by_label(selector)
            if locator.count() > 0:
                locator.first.click(timeout=5000)
                return
        except Exception:
            pass

        raise RuntimeError(f"Element not found for click: {selector!r}")

    def _do_type(self, page: Page, selector: str, value: str) -> None:
        """Type text into an element using multiple strategies."""
        if not selector and not value:
            return

        # Strategy 1: placeholder
        if selector:
            try:
                locator = page.get_by_placeholder(selector)
                if locator.count() > 0:
                    locator.first.click(timeout=3000)
                    locator.first.fill(value)
                    return
            except Exception:
                pass

        # Strategy 2: label
        if selector:
            try:
                locator = page.get_by_label(selector)
                if locator.count() > 0:
                    locator.first.click(timeout=3000)
                    locator.first.fill(value)
                    return
            except Exception:
                pass

        # Strategy 3: role textbox/searchbox
        for role in ["searchbox", "textbox", "combobox"]:
            try:
                locator = page.get_by_role(role)
                if locator.count() > 0:
                    locator.first.click(timeout=3000)
                    locator.first.fill(value)
                    return
            except Exception:
                pass

        # Strategy 4: CSS selector
        if selector:
            try:
                page.fill(selector, value, timeout=3000)
                return
            except Exception:
                pass

        # Strategy 5: active input element
        try:
            page.keyboard.type(value)
            return
        except Exception:
            pass

        raise RuntimeError(f"Could not type into: {selector!r}")

    def _do_recovery(self, step_index: int, task: str, start_url: str, strategy: str) -> StepResult:
        """Apply a recovery strategy and re-observe."""
        page = self.page

        if "scroll" in strategy:
            page.evaluate("window.scrollBy(0, 500)")
        elif "navigate_back" in strategy:
            page.go_back()
        elif "press_enter" in strategy:
            page.keyboard.press("Enter")
        elif "click_parent" in strategy:
            page.evaluate("document.activeElement?.parentElement?.click()")
        elif "wait" in strategy or "extend" in strategy:
            page.wait_for_timeout(3000)
        elif "relax" in strategy or "role_name" in strategy:
            page.wait_for_timeout(1000)
        else:
            page.wait_for_timeout(1000)

        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except PwTimeout:
            pass

        return self._observe(step_index, f"recovery:{strategy}", task, start_url)

    def _observe(self, step_index: int, action_desc: str, task: str, start_url: str) -> StepResult:
        """Capture current page state and verify."""
        page = self.page
        url = page.url
        title = page.title() or ""

        try:
            body_text = page.inner_text("body")[:5000]
        except Exception:
            body_text = title

        a11y = self._get_a11y_snapshot()

        vr = verify_step(
            url=url,
            page_text=f"{title}\n{body_text}",
            task=task,
            start_url=start_url,
        )

        return StepResult(
            step_index=step_index,
            action=action_desc,
            url=url,
            page_text=body_text[:2000],
            a11y_tree=a11y,
            verify=vr,
            failure_type=classify_failure(vr.reason) if not vr.passed else None,
        )

    def _get_a11y_snapshot(self) -> str:
        """Get compressed accessibility tree."""
        try:
            snapshot = self.page.accessibility.snapshot()
            return compress_a11y(snapshot or {}, max_chars=12000)
        except Exception:
            try:
                return compress_a11y(self.page.content()[:12000], max_chars=12000)
            except Exception:
                return ""
