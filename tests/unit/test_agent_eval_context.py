"""Tests for harness hardening — agent eval context isolation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shared_harness.eval_runner import evaluate_agent_task, run_agent_eval
from task1_agent.agent.loop import RunResult, StepResult


@pytest.mark.unit
def test_run_agent_eval_resets_context_between_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    instances: list[MagicMock] = []

    class FakeExecutor:
        def __init__(self, **kwargs: object) -> None:
            self.reset_calls = 0
            instances.append(self)

        def start(self) -> None:
            pass

        def close(self) -> None:
            pass

        def reset_context(self) -> None:
            self.reset_calls += 1

        def __call__(self, *args: object, **kwargs: object) -> StepResult:
            return StepResult(step_index=0, action="noop", url="https://example.com")

    def fake_run(**kwargs: object) -> RunResult:
        return RunResult(
            run_id=str(kwargs.get("run_id", "")),
            status="success",
            steps=[StepResult(step_index=0, action="task_complete", url="https://example.com")],
            final_url="https://example.com",
            extracted_result="ok",
        )

    monkeypatch.setattr("task1_agent.agent.browser.PlaywrightExecutor", FakeExecutor)
    monkeypatch.setattr("task1_agent.agent.loop.run", fake_run)

    import yaml
    from pathlib import Path

    path = Path("task1_agent/eval/tasks.yaml")
    train_tasks = yaml.safe_load(path.read_text(encoding="utf-8"))["tasks"]
    train_only = [t for t in train_tasks if t.get("split") == "train" and not t.get("smoke_only")][:3]
    monkeypatch.setattr(
        "shared_harness.eval_runner.load_tasks",
        lambda tasks_path=None: {"tasks": train_only},
    )

    results = run_agent_eval(split="train")
    assert len(results) == 3
    assert len(instances) == 1
    assert instances[0].reset_calls == 2


@pytest.mark.unit
def test_evaluate_agent_task_does_not_reset_context(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = MagicMock()
    executor.return_value = StepResult(step_index=0, action="noop")

    def fake_run(**kw: object) -> RunResult:
        return RunResult(
            run_id=str(kw["run_id"]),
            status="success",
            steps=[],
            final_url="https://example.com",
            extracted_result="x",
        )

    monkeypatch.setattr("task1_agent.agent.loop.run", fake_run)
    task = {
        "id": "solo",
        "domain": "example.com",
        "task_type": "extract",
        "description": "test",
        "start_url": "https://example.com",
        "split": "train",
    }
    evaluate_agent_task(task, executor=executor)
    executor.reset_context.assert_not_called()
