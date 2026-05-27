"""L0 heuristic verification + Blind Critic terminal gate."""

from __future__ import annotations

import os
from dataclasses import dataclass

from shared_harness.llm_parse import parse_model
from shared_harness.schemas.common import CriticVerdict


@dataclass
class VerifyResult:
    passed: bool
    reason: str = ""


def verify_step(
    *,
    url: str,
    expected_url_fragment: str | None = None,
    page_text: str = "",
    expected_keywords: list[str] | None = None,
) -> VerifyResult:
    """L0 heuristic check after each action step."""
    if expected_url_fragment and expected_url_fragment not in url:
        return VerifyResult(passed=False, reason=f"URL missing fragment: {expected_url_fragment!r}")

    if expected_keywords:
        lower_text = page_text.lower()
        missing = [kw for kw in expected_keywords if kw.lower() not in lower_text]
        if missing:
            return VerifyResult(passed=False, reason=f"Keywords not found: {missing}")

    return VerifyResult(passed=True)


def verify_via_blind_critic(
    task_description: str,
    final_a11y_tree: str,
    *,
    run_id: str | None = None,
) -> CriticVerdict:
    """Terminal gate: independent Tier1 YES/NO on final state.

    Only called when ENABLE_BLIND_CRITIC=true and all L0 steps passed.
    """
    from shared_harness.llm_router import complete
    from shared_harness.prompt_loader import load_prompt

    prompt_text = load_prompt("blind_critic")
    messages = [
        {"role": "system", "content": prompt_text},
        {"role": "user", "content": f"TASK: {task_description}\n\nFINAL A11Y TREE:\n{final_a11y_tree}"},
    ]
    result = complete(
        tier=1,
        call_site="agent_blind_critic",
        messages=messages,
        schema=CriticVerdict,
        run_id=run_id,
        task_type="agent",
        max_tokens=64,
    )
    return result  # type: ignore[return-value]


def blind_critic_enabled() -> bool:
    return os.environ.get("ENABLE_BLIND_CRITIC", "false").lower() in ("1", "true", "yes")
