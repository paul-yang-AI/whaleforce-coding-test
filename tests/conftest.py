"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared_harness.env import load_env

load_env()


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db.as_posix()}")
    # Reset schema flag so each test gets fresh schema
    import shared_harness.job_store as js

    js._schema_initialized = False


@pytest.fixture(autouse=True)
def _sec_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "SEC_USER_AGENT",
        "WhaleforceCodingTest TestUser test@example.com",
    )
    import shared_harness.edgar_client as ec

    ec.reset_throttle_for_tests()


@pytest.fixture
def mini_10k_html() -> str:
    path = Path(__file__).parent / "fixtures" / "mini_10k.html"
    return path.read_text(encoding="utf-8")
