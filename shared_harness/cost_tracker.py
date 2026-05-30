"""Thread-safe cost tracking with circuit breaker matrix."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from shared_harness.job_store import get_connection

_budget_lock = threading.RLock()


class BudgetExceededError(Exception):
    """Raised when a circuit breaker limit is hit."""


@dataclass(frozen=True)
class BudgetLimits:
    global_budget_usd: float = 20.0
    per_run_agent_usd: float = 0.50
    per_run_filing_usd: float = 0.30
    max_llm_calls_agent: int = 25
    max_llm_calls_filing: int = 5


def _limits() -> BudgetLimits:
    return BudgetLimits(
        global_budget_usd=float(os.environ.get("RUN_BUDGET_USD", "20")),
    )


def record_cost(
    *,
    run_id: str | None,
    tier: int,
    provider: str,
    model: str,
    call_site: str,
    attempt: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    usd: float,
) -> None:
    from datetime import datetime, timezone

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO cost_events
            (run_id, tier, provider, model, call_site, attempt, tokens_in, tokens_out, usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                tier,
                provider,
                model,
                call_site,
                attempt,
                tokens_in,
                tokens_out,
                usd,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_session_cost() -> float:
    conn = get_connection()
    try:
        row = conn.execute("SELECT COALESCE(SUM(usd), 0.0) AS total FROM cost_events").fetchone()
        return float(row["total"])
    finally:
        conn.close()


def get_run_cost(run_id: str) -> float:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(usd), 0.0) AS total FROM cost_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return float(row["total"])
    finally:
        conn.close()


def get_run_llm_call_count(run_id: str) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM cost_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row["cnt"])
    finally:
        conn.close()


def check_budget(
    run_id: str | None = None,
    *,
    task_type: str = "agent",
    before_call: bool = False,
) -> None:
    limits = _limits()
    session = get_session_cost()
    if session >= limits.global_budget_usd:
        raise BudgetExceededError(
            f"Global budget exceeded: ${session:.4f} >= ${limits.global_budget_usd:.2f}"
        )
    if run_id:
        run_cost = get_run_cost(run_id)
        cap = limits.per_run_agent_usd if task_type == "agent" else limits.per_run_filing_usd
        if run_cost >= cap:
            raise BudgetExceededError(
                f"Per-run budget exceeded: ${run_cost:.4f} >= ${cap:.2f}"
            )
        if before_call:
            max_calls = limits.max_llm_calls_agent if task_type == "agent" else limits.max_llm_calls_filing
            if get_run_llm_call_count(run_id) >= max_calls:
                raise BudgetExceededError(f"Max LLM calls exceeded: {max_calls}")


@contextmanager
def llm_budget_guard(
    run_id: str | None,
    *,
    task_type: str = "agent",
) -> Iterator[None]:
    """Serialize budget check → LLM call → cost record to prevent race overspend."""
    with _budget_lock:
        check_budget(run_id, task_type=task_type, before_call=True)
        yield
        check_budget(run_id, task_type=task_type)
