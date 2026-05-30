import pytest

from shared_harness.agent_ui import agent_heldout_badge, format_heldout_task_label


@pytest.mark.unit
def test_agent_heldout_badge_ok() -> None:
    emoji, label = agent_heldout_badge(failure_category="ok", status="success", silent_failure=0)
    assert emoji == "✅"
    assert "通過" in label


@pytest.mark.unit
def test_agent_heldout_badge_max_steps() -> None:
    emoji, label = agent_heldout_badge(failure_category="max_steps", status="failed")
    assert emoji == "❌"
    assert "max_steps" in label


@pytest.mark.unit
def test_format_heldout_task_label() -> None:
    task = {
        "id": "python_docs_heldout",
        "domain": "docs.python.org",
        "task_type": "navigate",
        "notes": "Frozen held-out",
    }
    row = {"failure_category": "ok", "status": "success", "silent_failure": 0}
    label = format_heldout_task_label(task, row)
    assert "python_docs_heldout" in label
    assert "✅" in label
