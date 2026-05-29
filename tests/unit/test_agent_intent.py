import pytest

from task1_agent.agent.intent import (
    extract_search_query,
    normalize_type_action,
    task_implies_search,
    task_implies_summary,
)


@pytest.mark.unit
def test_task_implies_search_english_and_chinese() -> None:
    assert task_implies_search("Search Wikipedia for 'Alan Turing'")
    assert task_implies_search("在 Google 搜尋 playwright")
    assert not task_implies_search("Navigate to example.com")


@pytest.mark.unit
def test_extract_search_query_quoted() -> None:
    assert extract_search_query("Go to wiki and search for 'Alan Turing'") == "Alan Turing"


@pytest.mark.unit
def test_extract_search_query_english_phrase() -> None:
    q = extract_search_query("Search DuckDuckGo for playwright browser automation")
    assert q is not None
    assert "playwright" in q.lower()


@pytest.mark.unit
def test_extract_search_query_chinese() -> None:
    assert extract_search_query("在 Google 搜尋 playwright 自動化") == "playwright 自動化"


@pytest.mark.unit
def test_extract_search_query_chinese_compound_summary() -> None:
    task = "幫我去搜尋富邦勇士然後摘要一下最近的比賽結果"
    assert extract_search_query(task) == "富邦勇士"
    assert task_implies_search(task)
    assert task_implies_summary(task)


@pytest.mark.unit
def test_task_implies_summary_chinese_info_request() -> None:
    task = "搜尋富邦勇士並給我一些資訊"
    assert task_implies_search(task)
    assert task_implies_summary(task)
    assert extract_search_query(task) == "富邦勇士"


@pytest.mark.unit
def test_normalize_type_action_fills_missing_value() -> None:
    sel, val, used = normalize_type_action(
        "Search Google for playwright automation",
        "input[name='q']",
        "",
    )
    assert used is True
    assert "playwright" in val.lower()
    assert sel == "input[name='q']"


@pytest.mark.unit
def test_normalize_type_action_keeps_existing_value() -> None:
    _, val, used = normalize_type_action("Search for X", "Search", "my query")
    assert used is False
    assert val == "my query"
