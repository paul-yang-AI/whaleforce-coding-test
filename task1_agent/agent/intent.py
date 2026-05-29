"""Map natural-language tasks to structured intent (generic, not site-specific)."""

from __future__ import annotations

import re

_SEARCH_TASK_RE = re.compile(
    r"\b(search|find|query|look\s*up)\b|搜[寻尋]|搜索|查詢|寻找|尋找",
    re.I,
)

_QUERY_COMPOUND_SPLIT = re.compile(
    r"(?:然後|然后|并|並|再|and then|then summarize|then|,\s*and\b|摘要|总结|總結|summarize|summary|整理|簡述)",
    re.I,
)

_QUERY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:search(?:\s+for)?|find|look\s+up|query)\s+(?:for\s+)?['\"]?(.+?)['\"]?"
        r"(?:\s+and|\s+on|\s+in|\s+verify|\s+then|\.|$)",
        re.I,
    ),
    re.compile(
        r"(?:搜[寻尋]|搜索|查詢|寻找|尋找)\s*[「『\"']?(.+?)"
        r"(?:然後|然后|并|並|再|摘要|总结|總結|[。\.]|$)",
        re.I,
    ),
    re.compile(
        r"(?:for|about|on)\s+['\"]([^'\"]+)['\"]",
        re.I,
    ),
]


def task_implies_search(task: str) -> bool:
    """True when the task description implies a search/find interaction."""
    return bool(_SEARCH_TASK_RE.search(task))


def task_implies_summary(task: str) -> bool:
    """True when the task asks for a summary/synthesis of page content."""
    return bool(
        re.search(
            r"摘要|总结|總結|summarize|summary|整理一下|簡述|"
            r"資訊|信息|告訴我|给我|給我|介绍|介紹|"
            r"some info|tell me about|give me",
            task,
            re.I,
        )
    )


def _trim_search_query(query: str) -> str:
    """Drop trailing compound clauses (e.g. 然後摘要…) from an extracted query."""
    parts = _QUERY_COMPOUND_SPLIT.split(query, maxsplit=1)
    return parts[0].strip(" '\"，。.;")


def extract_search_query(task: str) -> str | None:
    """Extract a search/query string from free-form task text."""
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", task)
    for q in reversed(quoted):
        cleaned = q.strip()
        if len(cleaned) >= 2:
            return cleaned

    for pattern in _QUERY_PATTERNS:
        match = pattern.search(task.strip())
        if not match:
            continue
        query = _trim_search_query(match.group(1))
        if len(query) >= 2:
            return query
    return None


def normalize_type_action(task: str, selector: str, value: str) -> tuple[str, str, bool]:
    """Repair type actions: fill missing value from task intent for search tasks."""
    selector = (selector or "").strip()
    value = (value or "").strip()
    if value:
        return selector, value, False
    if not task_implies_search(task):
        return selector, value, False
    query = extract_search_query(task)
    if query:
        return selector, query, True
    return selector, value, False
