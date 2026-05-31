"""Search URL fallback helpers (generic ?q= navigation)."""

from __future__ import annotations

import pytest

from task1_agent.agent.intent import build_search_fallback_url, extract_search_query


@pytest.mark.unit
def test_build_search_fallback_url() -> None:
    url = build_search_fallback_url(
        "https://duckduckgo.com/",
        "playwright browser automation",
    )
    assert url.startswith("https://duckduckgo.com/?")
    assert "q=playwright" in url


@pytest.mark.unit
def test_extract_search_query_from_quoted_task() -> None:
    task = "Search DuckDuckGo for 'playwright browser automation' and verify results."
    assert extract_search_query(task) == "playwright browser automation"
