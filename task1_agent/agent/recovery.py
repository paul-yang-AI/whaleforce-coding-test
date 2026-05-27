"""Classified recovery — route by FailureType to strategy table."""

from __future__ import annotations

from enum import Enum


class FailureType(str, Enum):
    TIMEOUT = "TIMEOUT"
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
    ACTION_NO_EFFECT = "ACTION_NO_EFFECT"
    WRONG_PAGE = "WRONG_PAGE"
    CAPTCHA_OR_LOGIN = "CAPTCHA_OR_LOGIN"


STRATEGY_TABLE: dict[FailureType, list[str]] = {
    FailureType.TIMEOUT: ["extend_wait", "simplify_dom", "replan"],
    FailureType.ELEMENT_NOT_FOUND: ["role_name_locator", "scroll_into_view", "relax_selector", "replan"],
    FailureType.ACTION_NO_EFFECT: ["click_parent", "press_enter", "wait_network"],
    FailureType.WRONG_PAGE: ["navigate_back", "replan"],
    FailureType.CAPTCHA_OR_LOGIN: ["blocked"],
}

MAX_RECOVERY_PER_STEP = 2


def get_next_strategy(
    failure_type: FailureType,
    attempted: list[str],
) -> str | None:
    """Return next untried strategy for this failure_type, or None if exhausted."""
    strategies = STRATEGY_TABLE.get(failure_type, [])
    for s in strategies:
        if s not in attempted:
            return s
    return None


def classify_failure(error_msg: str, *, timed_out: bool = False) -> FailureType:
    """Heuristic classification of a step failure into FailureType."""
    msg = error_msg.lower()
    if timed_out or "timeout" in msg:
        return FailureType.TIMEOUT
    if "captcha" in msg or "login" in msg or "blocked" in msg:
        return FailureType.CAPTCHA_OR_LOGIN
    if "not found" in msg or "no element" in msg or "locator" in msg:
        return FailureType.ELEMENT_NOT_FOUND
    if "no effect" in msg or "unchanged" in msg:
        return FailureType.ACTION_NO_EFFECT
    if "wrong" in msg or "unexpected" in msg or "navigation" in msg:
        return FailureType.WRONG_PAGE
    return FailureType.ELEMENT_NOT_FOUND
