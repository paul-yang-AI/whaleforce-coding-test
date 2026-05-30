"""Budget guard prevents concurrent overspend under tight cap."""

from __future__ import annotations

import threading

import pytest

from shared_harness.cost_tracker import BudgetExceededError, get_session_cost, llm_budget_guard, record_cost
from shared_harness.job_store import create_run


@pytest.mark.unit
def test_llm_budget_guard_blocks_second_caller_under_tight_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUN_BUDGET_USD", "0.01")
    run_id = create_run("agent")
    record_cost(
        run_id=run_id,
        tier=1,
        provider="test",
        model="m",
        call_site="test",
        attempt="primary",
        usd=0.009,
    )

    errors: list[str] = []

    def try_guard() -> None:
        try:
            with llm_budget_guard(run_id, task_type="agent"):
                record_cost(
                    run_id=run_id,
                    tier=1,
                    provider="test",
                    model="m",
                    call_site="test",
                    attempt="primary",
                    usd=0.002,
                )
        except BudgetExceededError as exc:
            errors.append(str(exc))

    t1 = threading.Thread(target=try_guard)
    t2 = threading.Thread(target=try_guard)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(errors) >= 1
    assert get_session_cost() <= 0.011 + 1e-6
