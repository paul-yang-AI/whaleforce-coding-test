"""Pure helpers for Browser Agent Streamlit page (unit-testable without Streamlit)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def agent_heldout_badge(
    *,
    failure_category: str,
    status: str = "",
    silent_failure: int = 0,
) -> tuple[str, str]:
    """Return (emoji, short label) for held-out task baseline outcome."""
    cat = failure_category or "unknown"
    if cat == "ok" and silent_failure == 0:
        return "✅", "基線預期通過"
    if cat == "silent_failure" or silent_failure:
        return "⚠️", "silent failure"
    if cat == "max_steps":
        return "❌", f"預期失敗 — {cat}"
    if cat in ("reasoning_failure", "outcome_verify_fail", "recovery_exhausted"):
        return "❌", f"預期失敗 — {cat}"
    if status == "blocked":
        return "🚫", "blocked"
    return "⚠️", f"基線 {cat}"


def format_heldout_task_label(
    task: dict[str, Any],
    baseline_row: dict[str, Any] | None,
) -> str:
    """Dropdown label: task id + domain + baseline badge."""
    tid = task.get("id", "")
    domain = task.get("domain", "")
    if baseline_row:
        emoji, blabel = agent_heldout_badge(
            failure_category=str(baseline_row.get("failure_category", "")),
            status=str(baseline_row.get("status", "")),
            silent_failure=int(baseline_row.get("silent_failure") or 0),
        )
        badge = f"{emoji} {blabel}"
    else:
        badge = "🔬 未跑基線"
    notes = (task.get("notes") or "").strip()
    note_bit = f" — {notes[:50]}…" if len(notes) > 50 else (f" — {notes}" if notes else "")
    return f"{tid} ({domain}, {task.get('task_type', '')}) · {badge}{note_bit}"


def baseline_by_task_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(r.get("task_id")): r for r in rows if r.get("task_id")}
