"""Browser Agent UI — submit task, Refresh status, Stop button."""

from __future__ import annotations

import json
import threading
import uuid

import streamlit as st

from shared_harness import job_store
from task1_agent.agent.loop import run as agent_run


def _get_run_steps(run_id: str) -> list[dict]:
    conn = job_store.get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM run_steps WHERE run_id = ? ORDER BY step_index",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_run_status(run_id: str) -> str | None:
    conn = job_store.get_connection()
    try:
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        return row["status"] if row else None
    finally:
        conn.close()


st.title("Browser Agent")
st.caption("Plan → Act → Observe → Verify → Reflect | Classified recovery | DB + Refresh")

task = st.text_area("Task description", value="Navigate to example.com and verify the title.")
start_url = st.text_input("Start URL (optional)", value="https://example.com")

col1, col2, col3 = st.columns(3)
submit = col1.button("Run Task", type="primary")
refresh = col2.button("Refresh")
stop = col3.button("Stop Task", type="secondary")

if "agent_run_id" not in st.session_state:
    st.session_state["agent_run_id"] = None
if "agent_cancel" not in st.session_state:
    st.session_state["agent_cancel"] = None

if submit:
    run_id = str(uuid.uuid4())
    cancel_event = threading.Event()
    st.session_state["agent_run_id"] = run_id
    st.session_state["agent_cancel"] = cancel_event

    job_store.create_run("agent", run_id=run_id)

    def _run_agent():
        agent_run(
            task_description=task,
            start_url=start_url or "https://example.com",
            run_id=run_id,
            cancel_event=cancel_event,
        )

    thread = threading.Thread(target=_run_agent, daemon=True)
    thread.start()
    st.success(f"Task submitted (run_id: `{run_id}`). Use **Refresh** to check progress.")

if stop:
    cancel = st.session_state.get("agent_cancel")
    if cancel and not cancel.is_set():
        cancel.set()
        st.warning("Stop signal sent. Task will cancel at next step boundary.")
    else:
        st.info("No active task to stop.")

run_id = st.session_state.get("agent_run_id")
if run_id and (refresh or submit):
    status = _get_run_status(run_id)
    if status:
        color = {
            "queued": "info",
            "running": "info",
            "success": "success",
            "failed": "error",
            "blocked": "warning",
            "cancelled": "warning",
        }.get(status, "info")
        getattr(st, color)(f"**Status**: {status}")

    steps = _get_run_steps(run_id)
    if steps:
        st.subheader(f"Steps ({len(steps)})")
        for s in steps:
            with st.expander(f"Step {s['step_index']} — {s['action']} [{s.get('status', '')}]"):
                if s.get("failure_type"):
                    st.caption(f"Failure: {s['failure_type']} → Recovery: {s.get('recovery_strategy', 'N/A')}")
                if s.get("log_json"):
                    try:
                        log = json.loads(s["log_json"])
                        st.json(log)
                    except (json.JSONDecodeError, TypeError):
                        st.text(s["log_json"])

        st.download_button(
            "Download run log (JSON)",
            data=json.dumps(steps, indent=2, default=str),
            file_name=f"run_{run_id}.json",
            mime="application/json",
        )
    elif status == "queued":
        st.info("Task is queued, waiting to start...")

st.divider()
st.markdown("""
**Supported**: Static sites, search engines, public pages without login/CAPTCHA.

**Known limitations**:
- No login/CAPTCHA bypass (task reports `blocked`)
- Tab-close does not guarantee immediate cancel (use Stop button)
- Single browser instance per container
""")
