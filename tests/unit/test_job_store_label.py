import sqlite3
from pathlib import Path

import pytest

import shared_harness.job_store as job_store


@pytest.mark.unit
def test_create_run_stores_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    job_store._schema_initialized = False

    run_id = job_store.create_run("agent", label="搜尋富邦勇士並給我一些資訊")
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT label FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row is not None
        assert row[0] == "搜尋富邦勇士並給我一些資訊"
    finally:
        conn.close()
        job_store._schema_initialized = False


@pytest.mark.unit
def test_list_recent_runs_includes_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test2.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    job_store._schema_initialized = False

    job_store.create_run("sec", label="MSFT 10-K")
    runs = job_store.list_recent_runs(limit=5, task_type="sec")
    assert runs
    assert runs[0]["label"] == "MSFT 10-K"
    job_store._schema_initialized = False
