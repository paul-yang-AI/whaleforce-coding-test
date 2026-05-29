"""SQLite job store with WAL mode for concurrent Streamlit + agent threads."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "whaleforce.db"
_lock = threading.Lock()
_schema_initialized = False


def _default_db_path() -> Path:
    import os

    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        return Path(url.removeprefix("sqlite:///"))
    return _DEFAULT_DB


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    global _schema_initialized
    with _lock:
        if not _schema_initialized:
            conn.executescript(
                """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                label TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                action TEXT,
                status TEXT,
                failure_type TEXT,
                recovery_strategy TEXT,
                log_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id)
            );
            CREATE TABLE IF NOT EXISTS cost_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                tier INTEGER,
                provider TEXT,
                model TEXT,
                call_site TEXT,
                attempt TEXT,
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                usd REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL
            );
            """
            )
            conn.commit()
            _schema_initialized = True
        _migrate_schema(conn)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "label" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN label TEXT")
        conn.commit()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_run(task_type: str, run_id: str | None = None, *, label: str | None = None) -> str:
    rid = run_id or str(uuid.uuid4())
    now = _utcnow()
    label = (label or "").strip() or None
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO runs (id, task_type, status, label, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (rid, task_type, "queued", label, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return rid


def mark_run(run_id: str, status: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE runs SET status = ?, updated_at = ? WHERE id = ?",
            (status, _utcnow(), run_id),
        )
        conn.commit()
    finally:
        conn.close()


def insert_step(
    run_id: str,
    step_index: int,
    *,
    action: str | None = None,
    status: str | None = None,
    failure_type: str | None = None,
    recovery_strategy: str | None = None,
    log_json: str | None = None,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO run_steps
            (run_id, step_index, action, status, failure_type, recovery_strategy, log_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, step_index, action, status, failure_type, recovery_strategy, log_json, _utcnow()),
        )
        conn.commit()
    finally:
        conn.close()


def list_recent_runs(*, limit: int = 30, task_type: str | None = None) -> list[dict]:
    """Recent UI runs for observability (not benchmark KPI)."""
    conn = get_connection()
    try:
        if task_type:
            rows = conn.execute(
                """
                SELECT r.id, r.task_type, r.status, r.label, r.created_at, r.updated_at,
                       COUNT(DISTINCT s.id) AS step_count,
                       COALESCE((SELECT SUM(usd) FROM cost_events c WHERE c.run_id = r.id), 0) AS usd_total,
                       COALESCE((SELECT COUNT(*) FROM cost_events c WHERE c.run_id = r.id), 0) AS llm_calls
                FROM runs r
                LEFT JOIN run_steps s ON s.run_id = r.id
                WHERE r.task_type = ?
                GROUP BY r.id
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (task_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT r.id, r.task_type, r.status, r.label, r.created_at, r.updated_at,
                       COUNT(DISTINCT s.id) AS step_count,
                       COALESCE((SELECT SUM(usd) FROM cost_events c WHERE c.run_id = r.id), 0) AS usd_total,
                       COALESCE((SELECT COUNT(*) FROM cost_events c WHERE c.run_id = r.id), 0) AS llm_calls
                FROM runs r
                LEFT JOIN run_steps s ON s.run_id = r.id
                GROUP BY r.id
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_run_steps(run_id: str) -> list[dict]:
    """Step timeline for a single run."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT step_index, action, status, failure_type, log_json, created_at "
            "FROM run_steps WHERE run_id = ? ORDER BY step_index, id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@contextmanager
def get_connection_ctx(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()
