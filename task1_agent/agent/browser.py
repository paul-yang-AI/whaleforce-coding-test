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
from task1_agent.agent.intent import extract_search_query, normalize_type_action, task_implies_search
from task1_agent.agent.loop import StepResult
from task1_agent.agent.recovery import FailureType, classify_failure
from task1_agent.agent.verify import VerifyResult, verify_navigation, verify_step

logger = logging.getLogger(__name__)

_SUBMIT_TASK_VERBS = ("search", "find", "query", "搜", "查")


def _task_implies_submit(task: str) -> bool:
    """Generic: typing in search/find tasks should submit (Enter), not site-specific."""
    if task_implies_search(task):
        return True
    t = task.lower()
    return any(w in t for w in _SUBMIT_TASK_VERBS)


_CONSENT_BUTTON_RE = re.compile(
    r"accept|agree|got it|continue|allow all|i understand|consent|"
    r"接受|同意|繼續|继续|全部接受|全部同意|拒絕全部|拒绝全部|關閉|关闭",
    re.I,
)

_CSS_SELECTOR_HINT = re.compile(r"^[#\.\[]|input\[|textarea\[|^\w+\[", re.I)


def _looks_like_css(selector: str) -> bool:
    return bool(selector and _CSS_SELECTOR_HINT.search(selector.strip()))


def _format_action_desc(action_type: str, selector: str, value: str) -> str:
    base = f"{action_type}:{selector or value or '?'}"
    if selector and value:
        return f"{base}={value}"
    return base


def _try_dismiss_consent_banner(page: Page) -> None:
    """Dismiss common cookie/consent overlays (generic button labels, not site-specific)."""
    for role in ("button", "link"):
        try:
            locator = page.get_by_role(role, name=_CONSENT_BUTTON_RE)
            if locator.count() > 0:
                locator.first.click(timeout=2000)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass


_LAUNCH_ARGS = ["--disable-dev-shm-usage", "--no-sandbox"]
_DEFAULT_TIMEOUT = 20000
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class PlaywrightExecutor:
    """Manages a single browser instance across multiple steps."""

    def __init__(self, *, headless: bool = True, timeout_ms: int = _DEFAULT_TIMEOUT):
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._last_planned_action: dict | None = None

    def start(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            args=_LAUNCH_ARGS,
            headless=self._headless,
        )
        self._open_context()

    def _open_context(self) -> None:
        if self._browser is None:
            raise RuntimeError("Executor not started")
        self._context = self._browser.new_context(user_agent=_USER_AGENT)
        self._page = self._context.new_page()
        self._page.set_default_timeout(self._timeout_ms)

    def reset_context(self) -> None:
        """Fresh BrowserContext + Page (isolates cookies/storage between eval tasks)."""
        if self._browser is None:
            raise RuntimeError("Executor not started")
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        self._context = None
        self._page = None
        self._open_context()

    def close(self) -> None:
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

    _DOWNLOAD_EXTENSIONS = frozenset({
        ".pdf", ".zip", ".gz", ".tar", ".exe", ".dmg",
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".csv", ".tsv", ".parquet",
    })

    def _is_download_url(self, url: str) -> bool:
        from urllib.parse import urlparse
        path = urlparse(url).path.lower()
        return any(path.endswith(ext) for ext in self._DOWNLOAD_EXTENSIONS)

    def _do_navigate(self, step_index: int, task: str, start_url: str) -> StepResult:
        """Navigate to start_url and observe page state."""
        if self._is_download_url(start_url):
            return StepResult(
                step_index=step_index,
                action=f"navigate:{start_url}",
                url="about:blank",
                error=f"URL 指向可下載檔案（非網頁），無法在瀏覽器中開啟：{start_url}",
                verify=VerifyResult(passed=False, reason="download_url_detected"),
                failure_type=FailureType.CAPTCHA_OR_LOGIN,
            )

        page = self.page
        if step_index == 0 and start_url:
            page.goto(start_url, wait_until="domcontentloaded", timeout=self._timeout_ms)
            _try_dismiss_consent_banner(page)

        page.wait_for_timeout(500)
        return self._observe(step_index, f"navigate:{start_url}", task, start_url)

    def _do_planned_action(
        self, step_index: int, task: str, start_url: str, planned_action: dict
    ) -> StepResult:
        """Execute an LLM-planned action."""
        self._last_planned_action = planned_action
        page = self.page
        action_type = planned_action.get("action", "none")
        selector = planned_action.get("selector", "")
        value = planned_action.get("value", "")
        used_intent_fallback = False

        if action_type == "type":
            selector, value, used_intent_fallback = normalize_type_action(task, selector, value)

        action_desc = _format_action_desc(action_type, selector, value)
        if used_intent_fallback:
            action_desc = f"{action_desc}+intent"

        prev_url = page.url

        if action_type == "click":
            self._do_click(page, selector)
        elif action_type == "type":
            self._do_type(page, selector, value, prefer_searchbox=task_implies_search(task))
            if value and _task_implies_submit(task):
                page.wait_for_timeout(300)
                page.keyboard.press("Enter")
                action_desc = f"{action_desc}+Enter"
        elif action_type == "scroll":
            page.evaluate("window.scrollBy(0, 400)")
        elif action_type == "press_key":
            page.keyboard.press(value or "Enter")
        elif action_type == "navigate":
            if value and self._is_download_url(value):
                return StepResult(
                    step_index=step_index,
                    action=action_desc,
                    url=self._safe_url(),
                    error=f"URL 指向可下載檔案：{value}",
                    verify=VerifyResult(passed=False, reason="download_url_detected"),
                    failure_type=FailureType.CAPTCHA_OR_LOGIN,
                )
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

        return self._observe(
            step_index,
            action_desc,
            task,
            start_url,
            prev_url=prev_url if action_type == "type" else None,
        )

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

    def _do_type(
        self,
        page: Page,
        selector: str,
        value: str,
        *,
        prefer_searchbox: bool = False,
    ) -> None:
        """Type text into an element using multiple strategies."""
        if not selector and not value:
            return

        if prefer_searchbox or value:
            for role in ["searchbox", "textbox", "combobox"]:
                try:
                    locator = page.get_by_role(role)
                    if locator.count() > 0:
                        locator.first.click(timeout=3000)
                        locator.first.fill(value)
                        return
                except Exception:
                    pass

        if selector and not _looks_like_css(selector):
            try:
                locator = page.get_by_placeholder(selector)
                if locator.count() > 0:
                    locator.first.click(timeout=3000)
                    locator.first.fill(value)
                    return
            except Exception:
                pass

            try:
                locator = page.get_by_label(selector)
                if locator.count() > 0:
                    locator.first.click(timeout=3000)
                    locator.first.fill(value)
                    return
            except Exception:
                pass

        if selector and _looks_like_css(selector):
            try:
                page.fill(selector, value, timeout=3000)
                return
            except Exception:
                pass

        for role in ["searchbox", "textbox", "combobox"]:
            try:
                locator = page.get_by_role(role)
                if locator.count() > 0:
                    locator.first.click(timeout=3000)
                    locator.first.fill(value)
                    return
            except Exception:
                pass

        if selector:
            try:
                page.fill(selector, value, timeout=3000)
                return
            except Exception:
                pass

        if value:
            try:
                page.keyboard.type(value)
                return
            except Exception:
                pass

        raise RuntimeError(f"Could not type into: {selector!r}")

    def _do_recovery(self, step_index: int, task: str, start_url: str, strategy: str) -> StepResult:
        """Apply a recovery strategy and re-observe."""
        page = self.page
        planned = self._last_planned_action or {}
        selector = str(planned.get("selector") or "")

        if "scroll" in strategy:
            page.evaluate("window.scrollBy(0, 500)")
            try:
                page.locator(":focus").scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
        elif "navigate_back" in strategy:
            page.go_back()
        elif "press_enter" in strategy:
            page.keyboard.press("Enter")
        elif "click_parent" in strategy:
            page.evaluate("document.activeElement?.parentElement?.click()")
        elif "network" in strategy:
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except PwTimeout:
                page.wait_for_timeout(2000)
        elif "extend" in strategy or strategy.startswith("recovery:wait"):
            page.wait_for_timeout(3000)
        elif "role_name" in strategy and selector:
            for role in ("button", "link", "textbox", "searchbox"):
                try:
                    loc = page.get_by_role(role, name=re.compile(re.escape(selector[:80]), re.I))
                    if loc.count() > 0:
                        loc.first.scroll_into_view_if_needed(timeout=3000)
                        if role in ("textbox", "searchbox"):
                            loc.first.click(timeout=3000)
                        else:
                            loc.first.click(timeout=3000)
                        break
                except Exception:
                    continue
        elif "relax" in strategy and selector:
            try:
                loc = page.get_by_text(selector[:60], exact=False)
                if loc.count() > 0:
                    loc.first.scroll_into_view_if_needed(timeout=3000)
                    loc.first.click(timeout=3000)
            except Exception:
                pass
        elif "replan" in strategy:
            page.wait_for_timeout(500)
        else:
            page.wait_for_timeout(1000)

        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except PwTimeout:
            pass

        return self._observe(step_index, f"recovery:{strategy}", task, start_url)

    def _observe(
        self,
        step_index: int,
        action_desc: str,
        task: str,
        start_url: str,
        *,
        prev_url: str | None = None,
    ) -> StepResult:
        """Capture current page state and verify."""
        page = self.page
        url = page.url
        title = page.title() or ""

        try:
            body_text = page.inner_text("body")[:5000]
        except Exception:
            body_text = title

        a11y = self._get_a11y_snapshot()

        page_content = f"{title}\n{body_text}"
        if step_index == 0 and action_desc.startswith("navigate:"):
            vr = verify_navigation(url=url, page_text=page_content, start_url=start_url)
        else:
            vr = verify_step(
                url=url,
                page_text=page_content,
                task=task,
                start_url=start_url,
                check_task_keywords=False,
            )
            if vr.passed and action_desc.endswith("+Enter") and task_implies_search(task):
                query = extract_search_query(task)
                if query and prev_url and url.rstrip("/") == prev_url.rstrip("/"):
                    q_lower = query.lower()
                    if q_lower not in url.lower() and q_lower not in page_content.lower():
                        vr = VerifyResult(
                            passed=False,
                            reason=f"Search submitted but page unchanged (query={query!r})",
                        )

        return StepResult(
            step_index=step_index,
            action=action_desc,
            url=url,
            page_text=body_text[:5000],
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
