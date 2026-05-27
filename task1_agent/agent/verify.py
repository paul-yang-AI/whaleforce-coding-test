"""L0 heuristic verification + Blind Critic terminal gate."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from shared_harness.llm_parse import parse_model
from shared_harness.schemas.common import CriticVerdict


@dataclass
class VerifyResult:
    passed: bool
    reason: str = ""


_ERROR_INDICATORS = [
    "this site can't be reached",
    "err_connection",
    "dns_probe",
    "net::err",
    "403 forbidden",
    "404 not found",
    "access denied",
]

_STOP_WORDS = frozenset(
    "the a an is are was were be been being have has had do does did "
    "will would shall should may might can could to of in for on with "
    "at by from and or but not no nor so yet it its that this these "
    "those there their them they we you i my me he she him her us our "
    "what which who whom whose when where how why if then than too also "
    "very just about up out into over after before above below between "
    "each all any both few more most other some such as go get make".split()
)


def _extract_task_keywords(task: str) -> list[str]:
    """Extract meaningful verification keywords from task description.

    Generic approach: extract proper nouns, domain names, and key phrases.
    No hardcoding for specific websites.
    """
    keywords = []

    urls = re.findall(r"https?://[^\s,]+", task)
    for url in urls:
        domain = urlparse(url).netloc.replace("www.", "")
        if domain:
            keywords.append(domain.split(".")[0])

    quoted = re.findall(r"['\"]([^'\"]+)['\"]", task)
    keywords.extend(quoted)

    return keywords


def verify_step(
    *,
    url: str,
    page_text: str = "",
    task: str = "",
    start_url: str = "",
    expected_url_fragment: str | None = None,
    expected_keywords: list[str] | None = None,
) -> VerifyResult:
    """L0 heuristic check after each action step.

    Generic verification — no hardcoded site-specific logic.
    """
    if not url or url == "about:blank":
        return VerifyResult(passed=False, reason="Page not loaded (blank URL)")

    lower_text = page_text.lower()
    for indicator in _ERROR_INDICATORS:
        if indicator in lower_text:
            return VerifyResult(passed=False, reason=f"Error page detected: {indicator}")

    if expected_url_fragment and expected_url_fragment not in url:
        return VerifyResult(passed=False, reason=f"URL missing fragment: {expected_url_fragment!r}")

    if start_url:
        expected_domain = urlparse(start_url).netloc.replace("www.", "")
        actual_domain = urlparse(url).netloc.replace("www.", "")
        if expected_domain and actual_domain and expected_domain != actual_domain:
            if not actual_domain.endswith(expected_domain):
                return VerifyResult(
                    passed=False,
                    reason=f"Domain mismatch: expected {expected_domain}, got {actual_domain}",
                )

    if expected_keywords:
        missing = [kw for kw in expected_keywords if kw.lower() not in lower_text]
        if missing:
            return VerifyResult(passed=False, reason=f"Keywords not found: {missing}")

    if len(page_text.strip()) < 50:
        return VerifyResult(passed=False, reason="Page content too short (possibly empty)")

    return VerifyResult(passed=True)


def verify_navigation(*, url: str, page_text: str, task: str, start_url: str) -> VerifyResult:
    """Verify that initial navigation succeeded (step 0)."""
    return verify_step(url=url, page_text=page_text, task=task, start_url=start_url)


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
