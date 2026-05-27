"""L1: recovery strategy routing — no repeat strategy for same failure_type."""

import pytest

from task1_agent.agent.recovery import (
    FailureType,
    MAX_RECOVERY_PER_STEP,
    STRATEGY_TABLE,
    classify_failure,
    get_next_strategy,
)


@pytest.mark.unit
def test_action_no_effect_returns_different_strategies() -> None:
    ft = FailureType.ACTION_NO_EFFECT
    first = get_next_strategy(ft, [])
    assert first is not None
    second = get_next_strategy(ft, [first])
    assert second is not None
    assert second != first


@pytest.mark.unit
def test_exhausted_returns_none() -> None:
    ft = FailureType.ACTION_NO_EFFECT
    all_strategies = STRATEGY_TABLE[ft]
    result = get_next_strategy(ft, all_strategies)
    assert result is None


@pytest.mark.unit
def test_captcha_blocked_strategy() -> None:
    ft = FailureType.CAPTCHA_OR_LOGIN
    strategy = get_next_strategy(ft, [])
    assert strategy == "blocked"


@pytest.mark.unit
def test_classify_timeout() -> None:
    assert classify_failure("page timed out", timed_out=True) == FailureType.TIMEOUT
    assert classify_failure("Timeout exceeded") == FailureType.TIMEOUT


@pytest.mark.unit
def test_classify_captcha() -> None:
    assert classify_failure("captcha detected") == FailureType.CAPTCHA_OR_LOGIN
    assert classify_failure("login required") == FailureType.CAPTCHA_OR_LOGIN


@pytest.mark.unit
def test_classify_element_not_found() -> None:
    assert classify_failure("Element not found on page") == FailureType.ELEMENT_NOT_FOUND


@pytest.mark.unit
def test_max_recovery_per_step_is_two() -> None:
    assert MAX_RECOVERY_PER_STEP == 2


@pytest.mark.unit
def test_wrong_page_strategies() -> None:
    ft = FailureType.WRONG_PAGE
    first = get_next_strategy(ft, [])
    assert first == "navigate_back"
    second = get_next_strategy(ft, [first])
    assert second == "replan"
