"""Agent state machine: Plan → Act → Observe → Verify → Reflect."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field

from shared_harness import job_store
from shared_harness.cost_tracker import BudgetExceededError
from task1_agent.agent.dom_serialize import compress_a11y
from task1_agent.agent.recovery import (
    FailureType,
    MAX_RECOVERY_PER_STEP,
    classify_failure,
    get_next_strategy,
)
from task1_agent.agent.verify import VerifyResult, blind_critic_enabled, verify_step, verify_via_blind_critic

logger = logging.getLogger(__name__)

MAX_STEPS = 10


@dataclass
class StepResult:
    step_index: int
    action: str
    url: str = ""
    page_text: str = ""
    a11y_tree: str = ""
    screenshot: bytes | None = None
    verify: VerifyResult = field(default_factory=lambda: VerifyResult(passed=True))
    failure_type: FailureType | None = None
    recovery_strategy: str | None = None
    error: str | None = None


@dataclass
class RunResult:
    run_id: str
    status: str = "success"
    steps: list[StepResult] = field(default_factory=list)
    final_url: str = ""
    error: str | None = None


def run(
    *,
    task_description: str,
    start_url: str = "https://example.com",
    run_id: str,
    cancel_event: threading.Event | None = None,
    execute_action: "ActionExecutor | None" = None,
) -> RunResult:
    """Execute agent loop. Playwright actions delegated to execute_action callable.

    execute_action(action: str, page_context: dict) -> StepResult
    If None, a no-op executor is used (for testing without browser).
    """
    job_store.mark_run(run_id, "running")
    result = RunResult(run_id=run_id)

    executor = execute_action or _noop_executor

    try:
        for step_idx in range(MAX_STEPS):
            if cancel_event and cancel_event.is_set():
                result.status = "cancelled"
                break

            step = _execute_step(
                step_index=step_idx,
                task_description=task_description,
                start_url=start_url,
                run_id=run_id,
                executor=executor,
                cancel_event=cancel_event,
            )
            result.steps.append(step)

            job_store.insert_step(
                run_id,
                step_idx,
                action=step.action,
                status="success" if step.verify.passed else "failed",
                failure_type=step.failure_type.value if step.failure_type else None,
                recovery_strategy=step.recovery_strategy,
                log_json=json.dumps({"url": step.url, "error": step.error}),
            )

            if step.error and step.failure_type == FailureType.CAPTCHA_OR_LOGIN:
                result.status = "blocked"
                result.error = step.error
                break

            if step.verify.passed:
                result.final_url = step.url
                continue

            # Recovery
            recovery_ok = _attempt_recovery(
                step=step,
                step_index=step_idx,
                run_id=run_id,
                task_description=task_description,
                executor=executor,
                cancel_event=cancel_event,
                result=result,
            )
            if not recovery_ok:
                result.status = "failed"
                result.error = f"Recovery exhausted at step {step_idx}: {step.verify.reason}"
                break

        # Terminal gate: Blind Critic
        if result.status == "success" and blind_critic_enabled() and result.steps:
            last_step = result.steps[-1]
            tree = compress_a11y(last_step.a11y_tree, max_chars=12000)
            try:
                verdict = verify_via_blind_critic(task_description, tree, run_id=run_id)
                if not verdict.passed:
                    result.status = "failed"
                    result.error = "Blind Critic rejected final state"
            except (BudgetExceededError, Exception) as exc:
                logger.warning("Blind Critic skipped: %s", exc)

    except BudgetExceededError as exc:
        result.status = "failed"
        result.error = f"Budget exceeded: {exc}"
    except Exception as exc:
        result.status = "failed"
        result.error = f"Unexpected error: {exc}"

    job_store.mark_run(run_id, result.status)
    return result


def _execute_step(
    *,
    step_index: int,
    task_description: str,
    start_url: str,
    run_id: str,
    executor: "ActionExecutor",
    cancel_event: threading.Event | None,
) -> StepResult:
    action = f"step_{step_index}"
    try:
        step = executor(action, {"task": task_description, "start_url": start_url, "step": step_index})
    except Exception as exc:
        step = StepResult(step_index=step_index, action=action, error=str(exc))
        step.verify = VerifyResult(passed=False, reason=str(exc))
        step.failure_type = classify_failure(str(exc))
    return step


def _attempt_recovery(
    *,
    step: StepResult,
    step_index: int,
    run_id: str,
    task_description: str,
    executor: "ActionExecutor",
    cancel_event: threading.Event | None,
    result: RunResult,
) -> bool:
    """Try up to MAX_RECOVERY_PER_STEP different strategies. Returns True if recovered."""
    attempted: list[str] = []
    failure_type = step.failure_type or FailureType.ELEMENT_NOT_FOUND

    for _ in range(MAX_RECOVERY_PER_STEP):
        if cancel_event and cancel_event.is_set():
            result.status = "cancelled"
            return False

        strategy = get_next_strategy(failure_type, attempted)
        if strategy is None or strategy == "blocked":
            return False

        attempted.append(strategy)
        logger.info("Recovery step %d: %s → %s", step_index, failure_type.value, strategy)

        job_store.insert_step(
            run_id,
            step_index,
            action=f"recovery:{strategy}",
            status="attempting",
            failure_type=failure_type.value,
            recovery_strategy=strategy,
        )

        try:
            retry_step = executor(
                f"recovery:{strategy}",
                {"task": task_description, "strategy": strategy, "step": step_index},
            )
        except Exception as exc:
            continue

        if retry_step.verify.passed:
            result.steps.append(retry_step)
            return True

    return False


# Type alias for action executor callable
from typing import Callable, Protocol


class ActionExecutor(Protocol):
    def __call__(self, action: str, context: dict) -> StepResult: ...


def _noop_executor(action: str, context: dict) -> StepResult:
    """Default no-op executor for testing."""
    return StepResult(
        step_index=context.get("step", 0),
        action=action,
        url="https://example.com",
        page_text="Example Domain",
        verify=VerifyResult(passed=True),
    )
