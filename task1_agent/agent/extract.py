"""Single-shot page extraction path (L2-style): navigate → LLM extract → verify."""

from __future__ import annotations

import logging

from shared_harness.schemas.common import PageExtraction
from task1_agent.agent.dom_serialize import compress_a11y

logger = logging.getLogger(__name__)

PAGE_CONTEXT_MAX = 8000
A11Y_CONTEXT_MAX = 10000

_ACT_VERBS = ("search", "form", "submit", "fill", "log in", "sign up", "sign in")
_EXTRACT_VERBS = (
    "extract",
    "summarize",
    "summary",
    "list all",
    "get all",
    "read the",
    "what is on",
    "header value",
    "user-agent",
)


def page_context_snippet(text: str, max_chars: int = PAGE_CONTEXT_MAX) -> str:
    """Head+tail truncation so planner/extractor sees start and end of long pages."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return f"{text[:half]}\n...[truncated {len(text) - max_chars} chars]...\n{text[-half:]}"


def infer_task_mode(task_description: str) -> str:
    """Route to extract (one-shot read) vs act (multi-step UI) — generic verbs only."""
    t = task_description.lower()
    if any(v in t for v in _ACT_VERBS):
        return "act"
    if any(v in t for v in _EXTRACT_VERBS):
        return "extract"
    if "find the" in t and "search" not in t:
        return "extract"
    if "navigate" in t and "verify" in t and "search" not in t:
        if not any(w in t for w in ("repository", "repo", "then go", "and open")):
            return "extract"
    return "act"


def extract_from_page(
    *,
    task_description: str,
    url: str,
    page_text: str,
    a11y_tree: str,
    run_id: str,
) -> str | None:
    """One LLM call to pull an answer from visible page content."""
    from shared_harness.cost_tracker import BudgetExceededError
    from shared_harness.llm_router import AllProvidersFailed, complete

    page_snippet = page_context_snippet(page_text, PAGE_CONTEXT_MAX)
    tree_snippet = compress_a11y(a11y_tree, max_chars=A11Y_CONTEXT_MAX) if a11y_tree else ""

    messages = [
        {
            "role": "system",
            "content": (
                "You extract information from web page content. "
                "IMPORTANT: Do NOT ask the user questions. All information is on the page.\n"
                "Use ONLY text that appears on the page — copy phrases verbatim where possible. "
                "Do NOT invent facts not present in the content.\n"
                "For summarize requests: return a short answer built from visible headings and "
                "sentences on the page (quoted snippets), not a generic essay.\n"
                "Return JSON: {\"result\": \"...\"}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"TASK: {task_description}\n\n"
                f"URL: {url}\n\n"
                f"PAGE CONTENT:\n{page_snippet}\n\n"
                f"ACCESSIBILITY TREE:\n{tree_snippet}\n\n"
                "Extract the answer."
            ),
        },
    ]

    try:
        parsed = complete(
            tier=1,
            call_site="agent_extract",
            messages=messages,
            schema=PageExtraction,
            run_id=run_id,
            task_type="agent",
            max_tokens=2048,
        )
        if isinstance(parsed, PageExtraction):
            return (parsed.result or "").strip()
        return None
    except BudgetExceededError as exc:
        logger.warning("Extract path budget exceeded: %s", exc)
        return None
    except AllProvidersFailed as exc:
        logger.error("Extract path all providers failed: %s", exc)
        return None
    except Exception as exc:
        logger.error("Extract path error (%s): %s", type(exc).__name__, exc)
        return None
