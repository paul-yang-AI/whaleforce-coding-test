"""Browser Agent UI — task presets, live status, classified recovery."""

from __future__ import annotations

import json
import threading
import time
import uuid

import streamlit as st

from shared_harness import job_store
from task1_agent.agent.browser import PlaywrightExecutor
from task1_agent.agent.loop import run as agent_run

_PRESETS = [
    {
        "label": "Custom task (enter below)",
        "task": "",
        "url": "",
    },
    {
        "label": "Navigate to Example.com",
        "task": "Navigate to example.com and verify the page loads successfully.",
        "url": "https://example.com",
    },
    {
        "label": "Hacker News — read top story",
        "task": "Go to Hacker News and find the title of the #1 ranked story.",
        "url": "https://news.ycombinator.com",
    },
    {
        "label": "Wikipedia — search Alan Turing",
        "task": "Search Wikipedia for 'Alan Turing' and verify the article page loads.",
        "url": "https://en.wikipedia.org",
    },
    {
        "label": "DuckDuckGo — search query",
        "task": "Search DuckDuckGo for 'playwright browser automation' and verify results appear.",
        "url": "https://duckduckgo.com",
    },
    {
        "label": "httpbin — view headers",
        "task": "Navigate to httpbin.org/headers and verify the JSON response is displayed.",
        "url": "https://httpbin.org/headers",
    },
    {
        "label": "GitHub — view cpython repo",
        "task": "Navigate to the Python cpython repository on GitHub.",
        "url": "https://github.com/python/cpython",
    },
]


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
st.caption("Plan → Act → Observe → Verify → Reflect | LLM-planned actions | Classified recovery")

preset_labels = [p["label"] for p in _PRESETS]
preset_choice = st.selectbox("Task presets", preset_labels, index=0)
selected_preset = _PRESETS[preset_labels.index(preset_choice)]

if selected_preset["task"]:
    default_task = selected_preset["task"]
    default_url = selected_preset["url"]
else:
    default_task = st.session_state.get("agent_task_text", "")
    default_url = st.session_state.get("agent_url_text", "")

task = st.text_area(
    "Task description",
    value=default_task,
    placeholder="Describe what the agent should do...",
    help="Natural language task. Simple navigation works best; search/form tasks use LLM planning.",
)
start_url = st.text_input(
    "Start URL",
    value=default_url,
    placeholder="https://example.com",
)

st.session_state["agent_task_text"] = task
st.session_state["agent_url_text"] = start_url

col1, col2, col3 = st.columns(3)
submit = col1.button("Run Task", type="primary")
refresh = col2.button("Refresh Status")
stop = col3.button("Stop Task", type="secondary")

if "agent_run_id" not in st.session_state:
    st.session_state["agent_run_id"] = None
if "agent_cancel" not in st.session_state:
    st.session_state["agent_cancel"] = None

if submit:
    if not task.strip():
        st.error("Please enter a task description.")
    elif not start_url.strip():
        st.error("Please enter a start URL.")
    else:
        run_id = str(uuid.uuid4())
        cancel_event = threading.Event()
        st.session_state["agent_run_id"] = run_id
        st.session_state["agent_cancel"] = cancel_event

        job_store.create_run("agent", run_id=run_id)

        def _run_agent():
            executor = PlaywrightExecutor(headless=True)
            executor.start()
            try:
                agent_run(
                    task_description=task,
                    start_url=start_url.strip(),
                    run_id=run_id,
                    cancel_event=cancel_event,
                    execute_action=executor,
                )
            finally:
                executor.close()

        thread = threading.Thread(target=_run_agent, daemon=True)
        thread.start()
        st.success(f"Task submitted! Run ID: `{run_id[:8]}...`")
        st.info("Click **Refresh Status** to see progress (agent runs in background).")

if stop:
    cancel = st.session_state.get("agent_cancel")
    if cancel and not cancel.is_set():
        cancel.set()
        st.warning("Stop signal sent. Task will cancel at next step boundary.")
    else:
        st.info("No active task to stop.")

run_id = st.session_state.get("agent_run_id")
if run_id and (refresh or submit):
    st.divider()
    status = _get_run_status(run_id)
    if status:
        status_colors = {
            "queued": "info",
            "running": "info",
            "success": "success",
            "failed": "error",
            "blocked": "warning",
            "cancelled": "warning",
        }
        color = status_colors.get(status, "info")
        status_icons = {
            "success": "Task completed successfully",
            "failed": "Task failed",
            "blocked": "Task blocked (login/CAPTCHA required)",
            "cancelled": "Task cancelled by user",
            "running": "Task running...",
            "queued": "Task queued, waiting to start...",
        }
        getattr(st, color)(f"**Status: {status.upper()}** — {status_icons.get(status, '')}")

    steps = _get_run_steps(run_id)
    if steps:
        st.subheader(f"Steps ({len(steps)})")

        for s in steps:
            action = s.get("action", "")
            step_status = s.get("status", "")

            if step_status == "success":
                icon = "white_check_mark"
            elif step_status == "failed":
                icon = "x"
            elif step_status == "attempting":
                icon = "arrows_counterclockwise"
            else:
                icon = "arrow_right"

            header = f":{icon}: Step {s['step_index']} — `{action}`"
            if s.get("failure_type"):
                header += f" | Recovery: {s.get('recovery_strategy', 'N/A')}"

            with st.expander(header, expanded=(step_status == "failed")):
                cols = st.columns(3)
                cols[0].caption(f"Status: **{step_status}**")
                if s.get("failure_type"):
                    cols[1].caption(f"Failure: {s['failure_type']}")
                if s.get("recovery_strategy"):
                    cols[2].caption(f"Strategy: {s['recovery_strategy']}")

                if s.get("log_json"):
                    try:
                        log = json.loads(s["log_json"])
                        if log.get("url"):
                            st.caption(f"URL: {log['url']}")
                        if log.get("error"):
                            st.error(f"Error: {log['error']}")
                        if log.get("action"):
                            st.caption(f"Action: {log['action']}")
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
    elif status == "running":
        st.info("Task is running... click **Refresh Status** again to check progress.")

st.divider()
with st.expander("How it works", expanded=False):
    st.markdown("""
**Architecture**: Plan → Act → Observe → Verify → Reflect

1. **Navigate** to the start URL
2. **Verify** page loaded (L0 heuristic: URL, content, no errors)
3. If task needs interaction → **LLM plans** the next action (click, type, etc.)
4. **Execute** the planned action
5. **Verify** result → **Recover** if failed (classified strategies, max 2 per step)
6. Repeat up to 10 steps (budget: max 5 LLM calls)

**Guards against infinite loops**:
- Max 10 steps total
- Max 2 recovery attempts per step (different strategies each time)
- Max 5 LLM calls per run (budget enforced)
- Same failure type never retries the same strategy
""")

with st.expander("Supported & Limitations", expanded=False):
    st.markdown("""
**Works well**:
- Simple navigation (any public website)
- Reading page content (Hacker News, Wikipedia, httpbin)
- Single-step search (DuckDuckGo, Wikipedia)

**Known limitations**:
- No login/CAPTCHA bypass (reports `blocked`)
- Multi-step form fills may be unreliable
- JavaScript-heavy SPAs may timeout
- Geo-restricted sites depend on server location
- Tab-close does not guarantee immediate cancel (use Stop button)
""")
