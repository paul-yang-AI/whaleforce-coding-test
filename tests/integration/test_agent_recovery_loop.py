"""L2: Agent loop with mock executor — recovery routing works correctly."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from shared_harness.job_store import create_run
from task1_agent.agent.loop import RunResult, StepResult, run
from task1_agent.agent.recovery import FailureType
from task1_agent.agent.verify import VerifyResult


def _make_failing_then_success_executor(fail_count: int = 2):
    """Returns executor that fails `fail_count` times then succeeds."""
    call_count = {"n": 0}

    def executor(action: str, context: dict) -> StepResult:
        call_count["n"] += 1
        step_idx = context.get("step", 0)
        if call_count["n"] <= fail_count:
            return StepResult(
                step_index=step_idx,
                action=action,
                url="https://example.com/wrong",
                page_text="wrong page",
                verify=VerifyResult(passed=False, reason="Element not found"),
                failure_type=FailureType.ELEMENT_NOT_FOUND,
                error="Element not found on page",
            )
        return StepResult(
            step_index=step_idx,
            action=action,
            url="https://example.com/target",
            page_text="Target content found",
            verify=VerifyResult(passed=True),
        )

    return executor


@pytest.mark.integration
def test_agent_recovery_succeeds_after_retry() -> None:
    run_id = create_run("agent")
    executor = _make_failing_then_success_executor(fail_count=1)
    result = run(
        task_description="Navigate to target page",
        start_url="https://example.com",
        run_id=run_id,
        execute_action=executor,
    )
    assert result.status == "success"


@pytest.mark.integration
def test_agent_recovery_exhausted_fails() -> None:
    run_id = create_run("agent")

    def always_fail(action: str, context: dict) -> StepResult:
        return StepResult(
            step_index=context.get("step", 0),
            action=action,
            url="https://example.com",
            verify=VerifyResult(passed=False, reason="still broken"),
            failure_type=FailureType.ACTION_NO_EFFECT,
            error="no effect",
        )

    result = run(
        task_description="Do something",
        start_url="https://example.com",
        run_id=run_id,
        execute_action=always_fail,
    )
    assert result.status == "failed"
    assert "Recovery exhausted" in (result.error or "")


@pytest.mark.integration
def test_agent_graceful_shutdown_on_cancel() -> None:
    run_id = create_run("agent")
    cancel = threading.Event()
    cancel.set()

    result = run(
        task_description="Will be cancelled",
        start_url="https://example.com",
        run_id=run_id,
        cancel_event=cancel,
    )
    assert result.status == "cancelled"


@pytest.mark.integration
def test_agent_blocked_on_captcha() -> None:
    run_id = create_run("agent")

    def captcha_executor(action: str, context: dict) -> StepResult:
        return StepResult(
            step_index=context.get("step", 0),
            action=action,
            url="https://example.com/captcha",
            verify=VerifyResult(passed=False, reason="captcha"),
            failure_type=FailureType.CAPTCHA_OR_LOGIN,
            error="captcha detected",
        )

    result = run(
        task_description="Try something",
        start_url="https://example.com",
        run_id=run_id,
        execute_action=captcha_executor,
    )
    assert result.status == "blocked"
