"""L1: agent verification — navigation vs terminal outcome (generic, no site hardcoding)."""

from __future__ import annotations

import pytest

from task1_agent.agent.loop import infer_max_steps
from task1_agent.agent.verify import (
    verify_extracted_result,
    verify_navigation,
    verify_step,
    verify_task_outcome,
)


@pytest.mark.unit
def test_navigation_does_not_require_quoted_task_terms() -> None:
    task = "Search Wikipedia for 'Alan Turing' and verify the article page loads."
    page = "Wikipedia\nThe Free Encyclopedia\nMain Page content here " * 5
    nav = verify_navigation(
        url="https://en.wikipedia.org/wiki/Main_Page",
        page_text=page,
        start_url="https://en.wikipedia.org",
    )
    assert nav.passed, nav.reason

    step = verify_step(
        url="https://en.wikipedia.org/wiki/Main_Page",
        page_text=page,
        task=task,
        start_url="https://en.wikipedia.org",
        check_task_keywords=True,
    )
    assert not step.passed


@pytest.mark.unit
def test_intermediate_step_skips_task_keywords() -> None:
    task = "Search DuckDuckGo for 'playwright browser automation'"
    page = "DuckDuckGo\nPrivacy. Simplified.\n" * 5
    vr = verify_step(
        url="https://duckduckgo.com/",
        page_text=page,
        task=task,
        start_url="https://duckduckgo.com",
        check_task_keywords=False,
    )
    assert vr.passed, vr.reason


@pytest.mark.unit
def test_verify_extracted_result_in_json_page() -> None:
    page = '{"headers": {"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0"}}'
    vr = verify_extracted_result("Mozilla/5.0 Chrome/120.0.0.0", page)
    assert vr.passed, vr.reason


@pytest.mark.unit
def test_verify_extracted_result_rejects_hallucination() -> None:
    page = '{"headers": {"User-Agent": "OtherAgent/1.0"}}'
    vr = verify_extracted_result("Mozilla/5.0 Chrome/120.0.0.0", page)
    assert not vr.passed


@pytest.mark.unit
def test_verify_task_outcome_requires_quoted_terms_on_final_page() -> None:
    task = "Search for 'Alan Turing' and verify results."
    fail = verify_task_outcome(
        task=task,
        url="https://example.com/",
        page_text="Example domain page with enough text " * 5,
        extracted_result="",
        start_url="https://example.com",
    )
    assert not fail.passed

    ok = verify_task_outcome(
        task=task,
        url="https://en.wikipedia.org/wiki/Alan_Turing",
        page_text="Alan Turing was a mathematician. " * 5,
        extracted_result="",
        start_url="https://en.wikipedia.org",
    )
    assert ok.passed, ok.reason


@pytest.mark.unit
def test_infer_max_steps_from_task_wording() -> None:
    assert infer_max_steps("Search DuckDuckGo for foo") == 15
    assert infer_max_steps("Extract the title from the page") == 12
    assert infer_max_steps("Go to example.com") == 10
    assert infer_max_steps("幫我去搜尋富邦勇士然後摘要一下最近的比賽結果") == 20
    assert infer_max_steps("搜尋富邦勇士並給我一些資訊") == 20
    assert infer_max_steps("在 Google 搜尋 playwright") == 15


@pytest.mark.unit
def test_task_implies_submit_generic_verbs() -> None:
    from task1_agent.agent.browser import _task_implies_submit

    assert _task_implies_submit("Search Wikipedia for 'Alan Turing'")
    assert _task_implies_submit("Find the top story on HN")
    assert not _task_implies_submit("Navigate to example.com and verify title")
    assert not _task_implies_submit("Help summarize the page")


@pytest.mark.unit
def test_infer_task_mode_routing() -> None:
    from task1_agent.agent.extract import infer_task_mode

    assert infer_task_mode("Search Wikipedia for 'Alan Turing'") == "act"
    assert infer_task_mode("Extract the User-Agent from the page") == "extract"
    assert infer_task_mode("Go to Hacker News and find the title of the #1 story") == "extract"
    assert infer_task_mode("Navigate to github.com/python/cpython and verify the repository title") == "act"
    assert infer_task_mode("Help summarize the page") == "extract"


@pytest.mark.unit
def test_page_context_snippet_head_tail() -> None:
    from task1_agent.agent.extract import page_context_snippet

    long_text = "A" * 5000 + "UNIQUE_TAIL" + "B" * 5000
    snippet = page_context_snippet(long_text, max_chars=1000)
    assert snippet.startswith("A")
    assert "truncated" in snippet


@pytest.mark.unit
def test_extract_path_after_navigate() -> None:
    from unittest.mock import patch

    from shared_harness import job_store
    from task1_agent.agent.loop import StepResult, run
    from task1_agent.agent.verify import VerifyResult

    run_id = job_store.create_run("agent")

    def executor(action: str, context: dict) -> StepResult:
        return StepResult(
            step_index=context.get("step", 0),
            action=action,
            url="https://example.com",
            page_text="Example Domain\nThis domain is for use in illustrative examples in documents.",
            a11y_tree="<heading>Example Domain</heading>",
            verify=VerifyResult(passed=True),
        )

    with patch("task1_agent.agent.loop.extract_from_page", return_value="Example Domain"):
        result = run(
            task_description="Navigate to example.com and verify the page title contains Example Domain.",
            start_url="https://example.com",
            run_id=run_id,
            execute_action=executor,
        )
    assert result.status == "success"
    assert result.extracted_result == "Example Domain"
    assert len(result.steps) == 2
