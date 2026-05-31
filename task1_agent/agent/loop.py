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
    MAX_RECOVERY_PER_ACTION,
    MAX_RECOVERY_PER_STEP,
    classify_failure,
    get_next_strategy,
)
from task1_agent.agent.extract import extract_from_page, infer_task_mode, page_context_snippet
from task1_agent.agent.verify import VerifyResult, blind_critic_enabled, verify_step, verify_task_outcome, verify_via_blind_critic

logger = logging.getLogger(__name__)

MAX_STEPS_DEFAULT = 10
MAX_STEPS_SEARCH = 15
MAX_STEPS_SEARCH_SUMMARY = 20
MAX_STEPS_EXTRACT = 12
_STUCK_TYPE_MIN_REPEATS = 3


def _is_stuck_type_loop(steps: list[StepResult], *, min_repeats: int = _STUCK_TYPE_MIN_REPEATS) -> bool:
    """Detect repeated type actions without URL change (e.g. search-box loops on Google)."""
    if len(steps) < min_repeats:
        return False
    recent = steps[-min_repeats:]
    if not all(s.action.startswith("type:") for s in recent):
        return False
    urls = {s.url.rstrip("/") for s in recent if s.url}
    return len(urls) <= 1


def infer_max_steps(task_description: str) -> int:
    """Heuristic step budget from task wording — generic, not site-specific."""
    from task1_agent.agent.intent import task_implies_search, task_implies_summary

    t = task_description.lower()
    implies_search = task_implies_search(task_description) or any(
        w in t for w in ("search", "find", "form", "submit", "fill")
    )
    if implies_search and task_implies_summary(task_description):
        return MAX_STEPS_SEARCH_SUMMARY
    if implies_search:
        return MAX_STEPS_SEARCH
    if any(w in t for w in ("extract", "navigate", "verify", "multiple")):
        return MAX_STEPS_EXTRACT
    return MAX_STEPS_DEFAULT


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
    extracted_result: str = ""


@dataclass
class RunResult:
    run_id: str
    status: str = "success"
    steps: list[StepResult] = field(default_factory=list)
    final_url: str = ""
    extracted_result: str = ""
    error: str | None = None


def _plan_next_action(
    task_description: str,
    current_url: str,
    page_text: str,
    a11y_tree: str,
    step_index: int,
    run_id: str,
    max_steps: int = MAX_STEPS_DEFAULT,
) -> dict | None:
    """Use LLM Tier1 to plan the next browser action.

    Returns None if LLM is unavailable or budget exceeded.
    Returns dict with action spec if planning succeeds.
    """
    from shared_harness.llm_router import AllProvidersFailed, complete
    from shared_harness.prompt_loader import load_prompt
    from shared_harness.schemas.common import AgentAction

    tree_snippet = compress_a11y(a11y_tree, max_chars=8000) if a11y_tree else ""
    page_snippet = page_context_snippet(page_text, max_chars=4000) if page_text else ""

    messages = [
        {
            "role": "system",
            "content": load_prompt("agent_plan"),
        },
        {
            "role": "user",
            "content": (
                f"TASK: {task_description}\n\n"
                f"CURRENT URL: {current_url}\n\n"
                f"PAGE CONTENT:\n{page_snippet}\n\n"
                f"ACCESSIBILITY TREE (compressed):\n{tree_snippet}\n\n"
                f"STEP: {step_index} of {max_steps}\n\n"
                "Plan the next action as JSON: {done, action, selector, value, reasoning, result}"
            ),
        },
    ]

    try:
        result = complete(
            tier=1,
            call_site="agent_plan",
            messages=messages,
            schema=AgentAction,
            run_id=run_id,
            task_type="agent",
            max_tokens=4096,
        )
        return result.model_dump() if hasattr(result, "model_dump") else None
    except BudgetExceededError as exc:
        logger.warning("LLM planning budget exceeded: %s", exc)
        return None
    except AllProvidersFailed as exc:
        logger.error("LLM planning all providers failed: %s", exc)
        return None
    except Exception as exc:
        logger.error("LLM planning unexpected error (%s): %s", type(exc).__name__, exc)
        return None


def _terminal_verify_kwargs(task_meta: dict | None) -> dict:
    if not task_meta:
        return {}
    return {
        "task_type": task_meta.get("task_type", "") or "",
        "success_hints": task_meta.get("success_hints"),
    }


def _attempt_search_url_fallback(
    *,
    step_index: int,
    task_description: str,
    start_url: str,
    run_id: str,
    executor: "ActionExecutor",
) -> StepResult | None:
    """Navigate to ?q= when type loop stuck — generic, not site-specific."""
    from task1_agent.agent.intent import build_search_fallback_url, extract_search_query, task_implies_search

    if not task_implies_search(task_description):
        return None
    query = extract_search_query(task_description)
    if not query:
        return None
    target = build_search_fallback_url(start_url, query)
    return executor(
        "search_url_fallback",
        {
            "step": step_index,
            "task": task_description,
            "start_url": start_url,
            "planned_action": {"action": "navigate", "value": target},
        },
    )


def run(
    *,
    task_description: str,
    start_url: str = "https://example.com",
    run_id: str,
    cancel_event: threading.Event | None = None,
    execute_action: "ActionExecutor | None" = None,
    task_meta: dict | None = None,
) -> RunResult:
    """Execute agent loop. Playwright actions delegated to execute_action callable.

    execute_action(action: str, page_context: dict) -> StepResult
    If None, a no-op executor is used (for testing without browser).
    """
    job_store.mark_run(run_id, "running")
    result = RunResult(run_id=run_id)
    search_fallback_used = False

    executor = execute_action or _noop_executor
    max_steps = infer_max_steps(task_description)

    try:
        for step_idx in range(max_steps):
            if cancel_event and cancel_event.is_set():
                result.status = "cancelled"
                break

            if step_idx == 0:
                # Step 0: navigate to start URL
                step = _execute_step(
                    step_index=step_idx,
                    task_description=task_description,
                    start_url=start_url,
                    run_id=run_id,
                    executor=executor,
                    cancel_event=cancel_event,
                )
            else:
                # Step 1+: LLM plans and executes next action
                step = _execute_planned_step(
                    step_index=step_idx,
                    task_description=task_description,
                    start_url=start_url,
                    run_id=run_id,
                    executor=executor,
                    cancel_event=cancel_event,
                    prev_step=result.steps[-1] if result.steps else None,
                    max_steps=max_steps,
                    task_meta=task_meta,
                )

            result.steps.append(step)

            log_data = {
                "url": step.url,
                "error": step.error,
                "action": step.action,
                "task": task_description,
            }
            if step.extracted_result:
                log_data["extracted_result"] = step.extracted_result

            job_store.insert_step(
                run_id,
                step_idx,
                action=step.action,
                status="success" if step.verify.passed else "failed",
                failure_type=step.failure_type.value if step.failure_type else None,
                recovery_strategy=step.recovery_strategy,
                log_json=json.dumps(log_data, default=str),
            )

            if step.error and step.failure_type == FailureType.CAPTCHA_OR_LOGIN:
                result.status = "blocked"
                result.error = step.error
                break

            # Check if LLM declared task complete (step 1+)
            if step.action in ("task_complete", "task_complete_rejected"):
                result.final_url = step.url
                if step.verify.passed:
                    result.status = "success"
                else:
                    result.status = "failed"
                    result.error = step.verify.reason or "Task outcome verification failed"
                break

            if step.verify.passed:
                if step_idx == 0:
                    if infer_task_mode(task_description) == "extract":
                        extract_step = _execute_extract_step(
                            step_index=1,
                            nav_step=step,
                            task_description=task_description,
                            start_url=start_url,
                            run_id=run_id,
                            task_meta=task_meta,
                        )
                        result.steps.append(extract_step)
                        job_store.insert_step(
                            run_id,
                            1,
                            action=extract_step.action,
                            status="success" if extract_step.verify.passed else "failed",
                            log_json=json.dumps(
                                {
                                    "url": extract_step.url,
                                    "action": extract_step.action,
                                    "extracted_result": extract_step.extracted_result,
                                    "error": extract_step.error,
                                },
                                default=str,
                            ),
                        )
                        result.final_url = extract_step.url
                        if extract_step.action == "task_complete":
                            result.status = "success"
                            result.extracted_result = extract_step.extracted_result
                        else:
                            result.status = "failed"
                            result.error = extract_step.error or extract_step.verify.reason
                        break
                    continue
                else:
                    if _is_stuck_type_loop(result.steps):
                        if not search_fallback_used:
                            fb = _attempt_search_url_fallback(
                                step_index=step_idx,
                                task_description=task_description,
                                start_url=start_url,
                                run_id=run_id,
                                executor=executor,
                            )
                            if fb is not None:
                                search_fallback_used = True
                                result.steps.append(fb)
                                job_store.insert_step(
                                    run_id,
                                    step_idx,
                                    action=fb.action,
                                    status="success" if fb.verify.passed else "failed",
                                    log_json=json.dumps(
                                        {
                                            "url": fb.url,
                                            "action": fb.action,
                                            "error": fb.error,
                                            "task": task_description,
                                        },
                                        default=str,
                                    ),
                                )
                                if fb.verify.passed:
                                    continue
                        result.status = "failed"
                        result.error = (
                            "Agent stuck: repeated type actions without page change. "
                            "For search tasks use type with a visible label as selector "
                            "and the query in value, then press_key Enter if needed. "
                            "For form tasks fill fields then click Submit or press Enter."
                        )
                        break
                    # Action step passed verification — continue to next LLM plan
                    continue

            if step_idx == 0:
                # Step 0 (navigation) failed — attempt recovery
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
            else:
                if not step.verify.passed and step.failure_type:
                    recovery_ok = _attempt_recovery(
                        step=step,
                        step_index=step_idx,
                        run_id=run_id,
                        task_description=task_description,
                        executor=executor,
                        cancel_event=cancel_event,
                        result=result,
                        max_attempts=MAX_RECOVERY_PER_ACTION,
                    )
                    if recovery_ok:
                        continue
                continue
        else:
            if result.status not in ("cancelled", "blocked"):
                # Max steps reached without completion — extract whatever we can
                result.status = "failed"
                result.error = "Max steps reached without task completion"

        # Capture extracted result from the final step
        if result.steps:
            last_step = result.steps[-1]
            if last_step.extracted_result:
                result.extracted_result = last_step.extracted_result

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
    """Execute step 0: initial navigation."""
    action = f"navigate:{start_url}"
    try:
        step = executor(action, {"task": task_description, "start_url": start_url, "step": step_index})
    except Exception as exc:
        step = StepResult(step_index=step_index, action=action, error=str(exc))
        step.verify = VerifyResult(passed=False, reason=str(exc))
        step.failure_type = classify_failure(str(exc))
    return step


def _execute_extract_step(
    *,
    step_index: int,
    nav_step: StepResult,
    task_description: str,
    start_url: str,
    run_id: str,
    task_meta: dict | None = None,
) -> StepResult:
    """Single-shot extract path after successful navigation (no action loop)."""
    extracted = extract_from_page(
        task_description=task_description,
        url=nav_step.url,
        page_text=nav_step.page_text,
        a11y_tree=nav_step.a11y_tree,
        run_id=run_id,
    )
    if not extracted:
        return StepResult(
            step_index=step_index,
            action="extract_failed",
            url=nav_step.url,
            page_text=nav_step.page_text,
            a11y_tree=nav_step.a11y_tree,
            verify=VerifyResult(passed=False, reason="Page extraction failed"),
            failure_type=FailureType.ACTION_NO_EFFECT,
            error="LLM extraction unavailable or returned empty result",
        )

    outcome = verify_task_outcome(
        task=task_description,
        url=nav_step.url,
        page_text=nav_step.page_text,
        extracted_result=extracted,
        start_url=start_url,
        **_terminal_verify_kwargs(task_meta),
    )
    step = StepResult(
        step_index=step_index,
        action="task_complete" if outcome.passed else "task_complete_rejected",
        url=nav_step.url,
        page_text=nav_step.page_text,
        a11y_tree=nav_step.a11y_tree,
        verify=outcome,
    )
    step.extracted_result = extracted
    if not outcome.passed:
        step.error = outcome.reason
    return step


def _execute_planned_step(
    *,
    step_index: int,
    task_description: str,
    start_url: str,
    run_id: str,
    executor: "ActionExecutor",
    cancel_event: threading.Event | None,
    prev_step: StepResult | None,
    max_steps: int = MAX_STEPS_DEFAULT,
    task_meta: dict | None = None,
) -> StepResult:
    """Use LLM to plan and execute the next action."""
    prev_url = prev_step.url if prev_step else ""
    prev_text = prev_step.page_text if prev_step else ""
    prev_tree = prev_step.a11y_tree if prev_step else ""

    plan = _plan_next_action(
        task_description, prev_url, prev_text, prev_tree, step_index, run_id, max_steps
    )

    if plan is None:
        return StepResult(
            step_index=step_index,
            action="plan_failed",
            url=prev_url,
            page_text=prev_text,
            a11y_tree=prev_tree,
            verify=VerifyResult(passed=False, reason="LLM planner unavailable"),
            failure_type=FailureType.ACTION_NO_EFFECT,
            error="LLM planner unavailable after primary and fallback",
        )

    if plan.get("done"):
        extracted = plan.get("result", "") or ""
        outcome = verify_task_outcome(
            task=task_description,
            url=prev_url,
            page_text=prev_text,
            extracted_result=extracted,
            start_url=start_url,
            **_terminal_verify_kwargs(task_meta),
        )
        step = StepResult(
            step_index=step_index,
            action="task_complete" if outcome.passed else "task_complete_rejected",
            url=prev_url,
            page_text=prev_text,
            a11y_tree=prev_tree,
            verify=outcome,
        )
        step.extracted_result = extracted
        return step

    action_desc = f"{plan.get('action', 'none')}:{plan.get('selector', '') or plan.get('value', '')}"
    try:
        step = executor(action_desc, {
            "task": task_description,
            "start_url": start_url,
            "step": step_index,
            "planned_action": plan,
        })
    except Exception as exc:
        step = StepResult(step_index=step_index, action=action_desc, error=str(exc))
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
    max_attempts: int = MAX_RECOVERY_PER_STEP,
) -> bool:
    """Try recovery strategies. Returns True if recovered."""
    attempted: list[str] = []
    failure_type = step.failure_type or FailureType.ELEMENT_NOT_FOUND

    for _ in range(max_attempts):
        if cancel_event and cancel_event.is_set():
            result.status = "cancelled"
            return False

        strategy = get_next_strategy(failure_type, attempted)
        if strategy is None or strategy == "blocked":
            return False

        attempted.append(strategy)
        logger.info("Recovery step %d: %s -> %s", step_index, failure_type.value, strategy)

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
                {"task": task_description, "strategy": strategy, "step": step_index, "start_url": ""},
            )
        except Exception:
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
        page_text="Example Domain\nThis domain is for use in illustrative examples.",
        verify=VerifyResult(passed=True),
    )
