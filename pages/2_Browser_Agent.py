"""Browser Agent UI — timeline view, auto-refresh, vivid result cards."""

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
        "category": "",
    },
    {
        "label": "🌐 Navigate to Example.com",
        "task": "Navigate to example.com and verify the page loads successfully.",
        "url": "https://example.com",
        "category": "navigation",
    },
    {
        "label": "📰 Hacker News — top story title",
        "task": "Go to Hacker News and find the title of the #1 ranked story.",
        "url": "https://news.ycombinator.com",
        "category": "extraction",
    },
    {
        "label": "📖 Wikipedia — search Alan Turing",
        "task": "Search Wikipedia for 'Alan Turing' and verify the article page loads.",
        "url": "https://en.wikipedia.org",
        "category": "search",
    },
    {
        "label": "🔍 DuckDuckGo — search query",
        "task": "Search DuckDuckGo for 'playwright browser automation' and verify results appear.",
        "url": "https://duckduckgo.com",
        "category": "search",
    },
    {
        "label": "🔧 httpbin — view headers",
        "task": "Navigate to httpbin.org/headers and extract the User-Agent header value.",
        "url": "https://httpbin.org/headers",
        "category": "extraction",
    },
    {
        "label": "🐍 GitHub — view cpython repo",
        "task": "Navigate to the Python cpython repository on GitHub and confirm the repo title.",
        "url": "https://github.com/python/cpython",
        "category": "navigation",
    },
]

_ACTION_ICONS = {
    "navigate": "🌐",
    "click": "👆",
    "type": "⌨️",
    "scroll": "📜",
    "press_key": "⏎",
    "task_complete": "🎯",
    "plan_failed": "⚠️",
    "recovery": "🔄",
}


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


def _action_icon(action: str) -> str:
    for key, icon in _ACTION_ICONS.items():
        if action.startswith(key):
            return icon
    return "▶️"


# --- Page Layout ---

st.markdown(
    '<h1 style="margin-bottom:0;">🤖 Browser Agent</h1>',
    unsafe_allow_html=True,
)
st.caption("Plan → Act → Observe → Verify → Reflect &nbsp;|&nbsp; LLM-planned actions &nbsp;|&nbsp; Classified recovery")

# Task input
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
    placeholder="Describe what the agent should do in natural language...",
    height=80,
)
start_url = st.text_input(
    "Start URL",
    value=default_url,
    placeholder="https://example.com",
)

st.session_state["agent_task_text"] = task
st.session_state["agent_url_text"] = start_url

# Action buttons
col1, col2, col3 = st.columns([2, 1, 1])
submit = col1.button("🚀 Run Task", type="primary", use_container_width=True)
refresh = col2.button("🔄 Refresh", use_container_width=True)
stop = col3.button("⏹️ Stop", type="secondary", use_container_width=True)

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
        st.success(f"✅ Task submitted! Run ID: `{run_id[:8]}…`")
        st.info("The agent is running in the background. Click **🔄 Refresh** to see progress.")

if stop:
    cancel = st.session_state.get("agent_cancel")
    if cancel and not cancel.is_set():
        cancel.set()
        st.warning("⏹️ Stop signal sent. Task will cancel at next step boundary.")
    else:
        st.info("No active task to stop.")

# Results display
run_id = st.session_state.get("agent_run_id")
if run_id and (refresh or submit):
    st.divider()
    status = _get_run_status(run_id)

    if status:
        status_config = {
            "success": ("✅", "Task completed successfully", "success"),
            "failed": ("❌", "Task failed", "error"),
            "blocked": ("🚫", "Blocked (login/CAPTCHA required)", "warning"),
            "cancelled": ("⏹️", "Cancelled by user", "warning"),
            "running": ("⏳", "Running...", "info"),
            "queued": ("🕐", "Queued, waiting to start...", "info"),
        }
        icon, msg, color = status_config.get(status, ("❓", status, "info"))
        getattr(st, color)(f"**{icon} {status.upper()}** — {msg}")

    steps = _get_run_steps(run_id)
    if steps:
        # Extract result
        extracted_result = None
        for s in reversed(steps):
            if s.get("log_json"):
                try:
                    log = json.loads(s["log_json"])
                    if log.get("extracted_result"):
                        extracted_result = log["extracted_result"]
                        break
                except (json.JSONDecodeError, TypeError):
                    pass

        # Result card (prominent)
        if extracted_result:
            st.markdown(
                f'<div style="background: linear-gradient(135deg, #dcfce7 0%, #d1fae5 100%); '
                f"border-radius: 12px; padding: 1.5rem; margin: 1rem 0; "
                f'border: 1px solid #86efac;">'
                f'<strong style="font-size: 1.1rem;">🎯 Result</strong><br>'
                f'<span style="font-size: 1rem; margin-top: 0.5rem; display: block;">'
                f"{extracted_result}</span></div>",
                unsafe_allow_html=True,
            )

        # Timeline view
        st.markdown(f"### Execution Timeline ({len(steps)} steps)")

        for i, s in enumerate(steps):
            action = s.get("action", "")
            step_status = s.get("status", "")
            icon = _action_icon(action)

            # Format action name
            if action.startswith("navigate:"):
                action_display = f"Navigate → {action[9:]}"
            elif action == "task_complete":
                action_display = "Task Complete"
            elif action == "plan_failed":
                action_display = "LLM Planning Failed"
            elif action.startswith("recovery:"):
                action_display = f"Recovery: {action[9:]}"
            elif ":" in action:
                parts = action.split(":", 1)
                action_display = f"{parts[0].title()} → {parts[1][:50]}"
            else:
                action_display = action

            # Status indicator
            if step_status == "success":
                border_color = "#10b981"
                bg_color = "#f0fdf4"
            elif step_status == "failed":
                border_color = "#ef4444"
                bg_color = "#fef2f2"
            elif step_status == "attempting":
                border_color = "#f59e0b"
                bg_color = "#fffbeb"
            else:
                border_color = "#6b7280"
                bg_color = "#f9fafb"

            # Parse log for URL
            url_display = ""
            error_display = ""
            if s.get("log_json"):
                try:
                    log = json.loads(s["log_json"])
                    if log.get("url"):
                        url_display = log["url"]
                    if log.get("error"):
                        error_display = log["error"]
                except (json.JSONDecodeError, TypeError):
                    pass

            # Render timeline item
            connector = "│" if i < len(steps) - 1 else " "
            st.markdown(
                f'<div style="border-left: 3px solid {border_color}; padding: 0.6rem 1rem; '
                f"margin-left: 1rem; margin-bottom: 0.3rem; background: {bg_color}; "
                f'border-radius: 0 8px 8px 0;">'
                f'<strong>{icon} Step {s["step_index"]}</strong> — {action_display}'
                + (f'<br><span style="font-size:0.8rem;color:#666;">📍 {url_display}</span>' if url_display else "")
                + (f'<br><span style="font-size:0.8rem;color:#dc2626;">⚠️ {error_display}</span>' if error_display else "")
                + (f'<br><span style="font-size:0.8rem;color:#666;">🔄 Recovery: {s["recovery_strategy"]}</span>' if s.get("recovery_strategy") else "")
                + "</div>",
                unsafe_allow_html=True,
            )

        st.divider()
        st.download_button(
            "📥 Download run log (JSON)",
            data=json.dumps(steps, indent=2, default=str),
            file_name=f"run_{run_id}.json",
            mime="application/json",
        )
    elif status == "running":
        st.info("⏳ Task is running... click **🔄 Refresh** to check progress.")

st.divider()

# Info sections
col_info1, col_info2 = st.columns(2)

with col_info1:
    with st.expander("🏗️ How it works"):
        st.markdown("""
**Agent Loop Architecture:**

1. **Navigate** → Load start URL, verify page renders
2. **Plan** → LLM analyzes page state (a11y tree + text)
3. **Act** → Execute planned action (click/type/scroll)
4. **Observe** → Capture new page state
5. **Verify** → Check if action had effect
6. **Reflect** → LLM decides: continue or done?
7. **Extract** → On completion, extract task-specific result

**Safety Guards:**
- Max 10 steps per task
- Max 25 LLM calls (budget enforced)
- Classified recovery (max 2 strategies per failure)
- Cost circuit breaker ($0.50/run limit)
""")

with col_info2:
    with st.expander("⚡ Capabilities & Limitations"):
        st.markdown("""
**Works reliably:**
- ✅ Navigation + page verification
- ✅ Content/data extraction
- ✅ Information lookup (news, wiki)
- ✅ Search tasks (DuckDuckGo, Wikipedia)
- ✅ Multi-step interactions

**Known limitations:**
- 🚫 No login/CAPTCHA bypass
- ⚠️ Complex multi-step forms (flaky)
- ⚠️ Heavy JS SPAs may timeout
- ⚠️ Geo-restricted content
- ⚠️ Requires valid LLM API key
""")
