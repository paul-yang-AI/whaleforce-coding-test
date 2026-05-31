"""Unit tests for private regression check helpers."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from shared_harness.regression_checks import (
    verify_agent_heldout_summary,
    verify_agent_train_results,
    verify_sec_heldout_summary,
    verify_sec_train_results,
)


@dataclass
class _Filing:
    ticker: str
    failure_category: str
    required_items_found: int
    required_items_total: int
    toc_stub_count: int = 0


@dataclass
class _Agent:
    task_id: str
    status: str
    silent_failure: int = 0


@pytest.mark.unit
def test_verify_sec_train_ok() -> None:
    results = [
        _Filing("MSFT", "ok", 4, 4),
        _Filing("INTC", "ok", 3, 3),
        _Filing("C", "ok", 3, 3),
    ]
    ok, msg = verify_sec_train_results(results)
    assert ok
    assert "3/3" in msg


@pytest.mark.unit
def test_verify_sec_train_rejects_wrong_required() -> None:
    results = [
        _Filing("MSFT", "ok", 3, 4),
        _Filing("INTC", "ok", 3, 3),
        _Filing("C", "ok", 3, 3),
    ]
    ok, _ = verify_sec_train_results(results)
    assert not ok


@pytest.mark.unit
def test_verify_agent_train_ok() -> None:
    results = [_Agent(f"t{i}", "success") for i in range(5)]
    ok, msg = verify_agent_train_results(results)
    assert ok
    assert "5/5" in msg


@pytest.mark.unit
def test_verify_sec_heldout_summary() -> None:
    ok, msg = verify_sec_heldout_summary(
        {"tier0_filings": 8, "tier0_ok": 6, "tier0_required_pass": 6}
    )
    assert ok
    assert "6/8" in msg


@pytest.mark.unit
def test_verify_agent_heldout_summary() -> None:
    ok, _ = verify_agent_heldout_summary({"heldout_tasks": 5, "heldout_ok": 3})
    assert ok
    ok2, _ = verify_agent_heldout_summary({"heldout_tasks": 5, "heldout_ok": 2})
    assert not ok2
