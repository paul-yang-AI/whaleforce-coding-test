import sqlite3
import threading

import pytest

from shared_harness.job_store import get_connection, insert_step
from shared_harness.cost_tracker import record_cost
from shared_harness.job_store import create_run


@pytest.mark.unit
def test_sqlite_wal_mode_enabled() -> None:
    conn = get_connection()
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()


@pytest.mark.unit
def test_sqlite_journal_mode_env_override(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "isolated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("SQLITE_JOURNAL_MODE", "TRUNCATE")
    conn = get_connection()
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "truncate"
    finally:
        conn.close()


@pytest.mark.unit
def test_sqlite_wal_concurrent_writes() -> None:
    run_id = create_run("stress")
    errors: list[str] = []
    n_threads = 10
    inserts_per_thread = 100

    def worker(tid: int) -> None:
        try:
            for i in range(inserts_per_thread):
                if i % 2 == 0:
                    record_cost(
                        run_id=run_id,
                        tier=1,
                        provider="test",
                        model="m",
                        call_site="test",
                        attempt="primary",
                        usd=0.0001,
                    )
                else:
                    insert_step(run_id, step_index=tid * inserts_per_thread + i, status="ok")
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    conn = get_connection()
    try:
        cost_rows = conn.execute("SELECT COUNT(*) FROM cost_events").fetchone()[0]
        step_rows = conn.execute("SELECT COUNT(*) FROM run_steps").fetchone()[0]
    finally:
        conn.close()
    assert cost_rows == n_threads * (inserts_per_thread // 2)
    assert step_rows == n_threads * (inserts_per_thread // 2)


@pytest.mark.unit
def test_list_recent_runs_includes_cost_and_steps() -> None:
    from shared_harness.job_store import list_recent_runs, mark_run

    run_id = create_run("agent")
    insert_step(run_id, 0, action="navigate:https://example.com", status="success")
    record_cost(
        run_id=run_id,
        tier=1,
        provider="test",
        model="m",
        call_site="test",
        attempt="primary",
        usd=0.01,
    )
    mark_run(run_id, "success")

    rows = list_recent_runs(limit=5, task_type="agent")
    match = [r for r in rows if r["id"] == run_id]
    assert match
    assert match[0]["step_count"] >= 1
    assert float(match[0]["usd_total"]) >= 0.01
