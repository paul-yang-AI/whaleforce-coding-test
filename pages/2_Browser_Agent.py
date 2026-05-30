"""瀏覽器代理 — 時間軸視圖、自動刷新、結果卡片。"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

import streamlit as st
import yaml

from shared_harness import job_store
from shared_harness.agent_ui import agent_heldout_badge, baseline_by_task_id, format_heldout_task_label
from task1_agent.agent.browser import PlaywrightExecutor
from task1_agent.agent.loop import run as agent_run

_ROOT = Path(__file__).resolve().parent.parent
_TASKS_YAML = _ROOT / "task1_agent" / "eval" / "tasks.yaml"
_AGENT_HELDOUT_BASELINE = _ROOT / "reports" / "agent_heldout_baseline.json"

_PRESETS = [
    {
        "label": "自訂任務（在下方輸入）",
        "task": "",
        "url": "",
        "category": "",
    },
    {
        "label": "🌐 導航至 Example.com",
        "task": "Navigate to example.com and verify the page loads successfully.",
        "url": "https://example.com",
        "category": "navigation",
    },
    {
        "label": "📰 Hacker News — 頭條標題",
        "task": "Go to Hacker News and find the title of the #1 ranked story.",
        "url": "https://news.ycombinator.com",
        "category": "extraction",
    },
    {
        "label": "📖 Wikipedia — 搜尋 Alan Turing",
        "task": "Search Wikipedia for 'Alan Turing' and verify the article page loads.",
        "url": "https://en.wikipedia.org",
        "category": "search",
    },
    {
        "label": "🔧 httpbin — 檢視 Headers",
        "task": "Navigate to httpbin.org/headers and extract the User-Agent header value.",
        "url": "https://httpbin.org/headers",
        "category": "extraction",
    },
    {
        "label": "🐍 GitHub — cpython 儲存庫",
        "task": "Navigate to the Python cpython repository on GitHub and confirm the repo title.",
        "url": "https://github.com/python/cpython",
        "category": "navigation",
    },
]


def _load_tasks_split(split: str) -> list[dict]:
    if not _TASKS_YAML.exists():
        return []
    data = yaml.safe_load(_TASKS_YAML.read_text(encoding="utf-8"))
    return [
        t
        for t in data.get("tasks", [])
        if t.get("split") == split and not t.get("smoke_only")
    ]


def _load_heldout_baseline() -> tuple[dict[str, dict], dict]:
    if not _AGENT_HELDOUT_BASELINE.exists():
        return {}, {}
    try:
        payload = json.loads(_AGENT_HELDOUT_BASELINE.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    rows = payload.get("heldout", [])
    return baseline_by_task_id(rows), payload.get("summary", {})


def _start_agent_run(task: str, start_url: str) -> None:
    if _is_agent_running():
        st.error("已有任務執行中，無法同時啟動多個代理。")
        return
    if not task.strip():
        st.error("請輸入任務描述。")
        return
    if not start_url.strip():
        st.error("請輸入起始 URL。")
        return

    run_id = str(uuid.uuid4())
    cancel_event = threading.Event()
    st.session_state["agent_run_id"] = run_id
    st.session_state["agent_cancel"] = cancel_event

    job_store.create_run("agent", run_id=run_id, label=task[:120])

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
    st.session_state["agent_auto_refresh"] = True
    st.success(f"✅ 任務已提交！執行 ID：`{run_id[:8]}…`")


def _render_task_form(
    *,
    key_prefix: str,
    default_task: str,
    default_url: str,
) -> tuple[str, str]:
    task = st.text_area(
        "任務描述",
        value=default_task,
        placeholder="以自然語言描述代理應執行的操作…",
        height=80,
        key=f"{key_prefix}_task",
    )
    start_url = st.text_input(
        "起始 URL",
        value=default_url,
        placeholder="https://example.com",
        key=f"{key_prefix}_url",
    )
    st.session_state["agent_task_text"] = task
    st.session_state["agent_url_text"] = start_url

    if start_url.strip() and "google.com" in start_url.strip().lower():
        st.warning(
            "⚠️ **Google 不建議用於 demo**：consent 橫幅與動態 DOM 易導致 agent 在 `type` 迴圈中卡住。"
        )
    return task, start_url


def _render_run_buttons(key_prefix: str) -> None:
    _agent_running = _is_agent_running()
    if _agent_running:
        st.warning("⏳ 已有任務執行中，請等待完成或按「停止」。")

    col1, col2 = st.columns([3, 1])
    submit = col1.button(
        "🚀 執行任務",
        type="primary",
        use_container_width=True,
        disabled=_agent_running,
        key=f"{key_prefix}_submit",
    )
    stop = col2.button(
        "⏹️ 停止",
        type="secondary",
        use_container_width=True,
        key=f"{key_prefix}_stop",
    )

    if submit:
        _start_agent_run(
            st.session_state.get("agent_task_text", ""),
            st.session_state.get("agent_url_text", ""),
        )

    if stop:
        cancel = st.session_state.get("agent_cancel")
        if cancel and not cancel.is_set():
            cancel.set()
            st.session_state["agent_auto_refresh"] = False
            st.warning("⏹️ 已發送停止訊號，任務將在下一步邊界取消。")
        else:
            st.info("目前沒有進行中的任務。")


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


def _is_agent_running() -> bool:
    run_id = st.session_state.get("agent_run_id")
    if not run_id:
        return False
    status = _get_run_status(run_id)
    return status in ("running", "queued")


def _status_banner_html(status: str) -> str:
    status_config = {
        "success": ("✅", "任務成功完成", "#dcfce7", "#166534", "#86efac"),
        "failed": ("❌", "任務失敗", "#fef2f2", "#991b1b", "#fecaca"),
        "blocked": ("🚫", "被阻擋（需要登入/CAPTCHA）", "#fffbeb", "#92400e", "#fde68a"),
        "cancelled": ("⏹️", "已被使用者取消", "#fffbeb", "#92400e", "#fde68a"),
        "running": ("⏳", "執行中…", "#eff6ff", "#1e40af", "#bfdbfe"),
        "queued": ("🕐", "排隊中，等待啟動…", "#f9fafb", "#374151", "#e5e7eb"),
    }
    icon, msg, bg, fg, border = status_config.get(
        status, ("❓", status, "#f9fafb", "#374151", "#e5e7eb")
    )
    return (
        f'<div style="background:{bg};color:{fg};border:1px solid {border};'
        f'border-radius:8px;padding:0.65rem 0.9rem;margin:0.5rem 0;">'
        f"<strong>{icon} {status.upper()}</strong> — {msg}</div>"
    )


def _format_step_line(s: dict) -> str:
    action = s.get("action", "")
    step_status = s.get("status", "")
    step_icon = _action_icon(action)

    if action.startswith("navigate:"):
        action_display = f"導航 → {action[9:]}"
    elif action == "task_complete":
        action_display = "任務完成"
    elif action == "task_complete_rejected":
        action_display = "任務完成但結果驗證失敗"
    elif action == "plan_failed":
        action_display = "LLM 規劃失敗"
    elif action.startswith("recovery:"):
        action_display = f"恢復：{action[9:]}"
    elif ":" in action:
        parts = action.split(":", 1)
        action_display = f"{parts[0].title()} → {parts[1][:50]}"
    else:
        action_display = action

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

    extra = ""
    if url_display:
        extra += f'<br><span style="font-size:0.8rem;color:#666;">📍 {url_display}</span>'
    if error_display:
        extra += f'<br><span style="font-size:0.8rem;color:#dc2626;">⚠️ {error_display}</span>'
    if s.get("recovery_strategy"):
        extra += (
            f'<br><span style="font-size:0.8rem;color:#666;">🔄 恢復策略：'
            f'{s["recovery_strategy"]}</span>'
        )

    return (
        f'<div style="border-left: 3px solid {border_color}; padding: 0.6rem 1rem; '
        f"margin-left: 1rem; margin-bottom: 0.3rem; background: {bg_color}; "
        f'border-radius: 0 8px 8px 0;">'
        f'<strong>{step_icon} 步驟 {s["step_index"]}</strong> — {action_display}{extra}</div>'
    )


def _render_agent_run_panel(
    run_id: str,
    *,
    include_download: bool = True,
    show_status: bool = True,
) -> str | None:
    """Render status + timeline for one run. Returns run status."""
    status = _get_run_status(run_id)
    if not status:
        return None

    if show_status:
        st.markdown(_status_banner_html(status), unsafe_allow_html=True)

    steps = _get_run_steps(run_id)
    if steps:
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

        if extracted_result:
            st.markdown(
                f'<div style="background: linear-gradient(135deg, #dcfce7 0%, #d1fae5 100%); '
                f"border-radius: 12px; padding: 1.5rem; margin: 1rem 0; "
                f'border: 1px solid #86efac;">'
                f'<strong style="font-size: 1.1rem;">🎯 執行結果</strong><br>'
                f'<span style="font-size: 1rem; margin-top: 0.5rem; display: block;">'
                f"{extracted_result}</span></div>",
                unsafe_allow_html=True,
            )

        st.markdown(f"### 執行時間軸（{len(steps)} 步）")
        st.markdown("".join(_format_step_line(s) for s in steps), unsafe_allow_html=True)

        if include_download:
            st.divider()
            st.download_button(
                "📥 下載執行紀錄（JSON）",
                data=json.dumps(steps, indent=2, default=str),
                file_name=f"run_{run_id}.json",
                mime="application/json",
                key=f"download_run_{run_id}",
            )
    elif status in ("running", "queued"):
        st.markdown(
            '<p style="color:#6b7280;margin:0.5rem 0;">等待第一步完成…</p>',
            unsafe_allow_html=True,
        )

    return status


@st.fragment(run_every=3)
def _agent_live_progress(run_id: str) -> None:
    """Lightweight polling UI — markdown only, no alerts/download buttons."""
    status = _get_run_status(run_id)
    if not status:
        return
    steps = _get_run_steps(run_id)
    st.markdown(_status_banner_html(status), unsafe_allow_html=True)
    if steps:
        latest = steps[-1]
        action = latest.get("action") or "—"
        st.markdown(
            f"**進行中** · 已完成 **{len(steps)}** 步 · 最新：`{action}`",
        )
        st.markdown("".join(_format_step_line(s) for s in steps), unsafe_allow_html=True)
    else:
        st.markdown(
            '<p style="color:#6b7280;margin:0.25rem 0;">等待第一步完成…</p>',
            unsafe_allow_html=True,
        )
    if status not in ("running", "queued"):
        st.session_state["agent_auto_refresh"] = False
        st.rerun()


# --- Page Layout ---

st.markdown(
    '<h1 style="margin-bottom:0;">🤖 瀏覽器自動化代理</h1>',
    unsafe_allow_html=True,
)
st.caption(
    "計畫 → 執行 → 觀察 → 驗證 → 反思 &nbsp;|&nbsp; "
    "Train KPI 5/5（Eval） &nbsp;|&nbsp; Held-out 基線見「泛化驗證」分頁"
)

if "agent_run_id" not in st.session_state:
    st.session_state["agent_run_id"] = None
if "agent_cancel" not in st.session_state:
    st.session_state["agent_cancel"] = None

tab_train, tab_heldout, tab_custom = st.tabs(
    ["📋 基準任務（Train）", "🔬 泛化驗證（Held-out）", "✏️ 自訂任務"]
)

with tab_train:
    st.markdown(
        "Train eval **5/5** regression contract（`tasks.yaml` split=train）。"
        "不在此分頁的 DuckDuckGo 等 held-out 任務請至「泛化驗證」。"
    )
    preset_labels = [p["label"] for p in _PRESETS]
    preset_choice = st.selectbox("任務預設", preset_labels, index=0, key="train_preset")
    selected_preset = _PRESETS[preset_labels.index(preset_choice)]
    if selected_preset["task"]:
        t_default, u_default = selected_preset["task"], selected_preset["url"]
    else:
        t_default = st.session_state.get("agent_task_text", "")
        u_default = st.session_state.get("agent_url_text", "")
    _render_task_form(key_prefix="train", default_task=t_default, default_url=u_default)
    _render_run_buttons("train")

with tab_heldout:
    st.markdown(
        "Held-out **不在 train KPI 內**；徽章來自 `reports/agent_heldout_baseline.json`。"
        "線上執行結果可能因網站/速率限制與離線基線略有差異。"
    )
    baseline_map, summary = _load_heldout_baseline()
    if summary:
        st.caption(
            f"離線基線：**{summary.get('heldout_ok', '?')}/{summary.get('heldout_tasks', '?')}** "
            f"`failure_category=ok`（詳見 Eval → Held-out 基線）。"
        )
    elif _AGENT_HELDOUT_BASELINE.exists() is False:
        st.caption("執行 `python scripts/run_agent_heldout_baseline.py` 產生基線報告。")

    heldout_tasks = _load_tasks_split("heldout")
    if not heldout_tasks:
        st.info("tasks.yaml 中尚無 held-out 任務。")
    else:
        labels = [format_heldout_task_label(t, baseline_map.get(t["id"])) for t in heldout_tasks]
        choice = st.selectbox("選擇 held-out 任務", labels, index=0, key="heldout_select")
        selected = heldout_tasks[labels.index(choice)]
        row = baseline_map.get(selected["id"])
        if row:
            emoji, blabel = agent_heldout_badge(
                failure_category=str(row.get("failure_category", "")),
                status=str(row.get("status", "")),
                silent_failure=int(row.get("silent_failure") or 0),
            )
            st.info(f"{emoji} **基線預期**：{blabel}（steps={row.get('steps', '—')}）。")
        elif selected.get("notes"):
            st.info(selected["notes"])
        _render_task_form(
            key_prefix="heldout",
            default_task=selected.get("description", ""),
            default_url=selected.get("start_url", ""),
        )
        _render_run_buttons("heldout")

with tab_custom:
    st.markdown("任意自然語言任務 — **不計入** train/held-out KPI。")
    _render_task_form(
        key_prefix="custom",
        default_task=st.session_state.get("agent_task_text", ""),
        default_url=st.session_state.get("agent_url_text", ""),
    )
    _render_run_buttons("custom")

# Results display — shared across tabs
run_id = st.session_state.get("agent_run_id")
if run_id:
    st.divider()
    status = _get_run_status(run_id)
    if status in ("running", "queued") and st.session_state.get("agent_auto_refresh"):
        _agent_live_progress(run_id)
    else:
        _render_agent_run_panel(run_id)
        if status in ("success", "failed", "blocked", "cancelled"):
            st.session_state["agent_auto_refresh"] = False

st.divider()

# Info sections
col_info1, col_info2 = st.columns(2)

with col_info1:
    with st.expander("🏗️ 運作原理"):
        st.markdown("""
**代理迴圈架構：**

1. **導航** → 載入起始 URL，確認頁面渲染
2. **抽取路徑**（extract/list/summarize）→ 單次 LLM 從頁面讀取；**動作路徑**（search/form）→ 多步 plan/act
3. **規劃** → LLM 分析頁面狀態（a11y 樹 + 文字）
3. **執行** → 執行規劃的動作（點擊/輸入/捲動）
4. **觀察** → 擷取新頁面狀態
5. **驗證** → 確認動作是否生效
6. **反思** → LLM 判斷：繼續或完成？
7. **抽取** → 完成後抽取任務特定結果

**安全防護：**
- 每任務 10–20 步（search + 資訊整理較多）
- 完成時驗證結果是否在頁面中（防 LLM 幻覺）
- 最多 25 次 LLM 呼叫（預算控制）
- 分類式恢復（每次失敗最多 2 種策略）
- 成本熔斷器（$0.50/次 上限）
""")

with col_info2:
    with st.expander("⚡ 能力與限制"):
        st.markdown("""
**穩定支援：**
- ✅ 頁面導航 + 驗證
- ✅ 內容/資料抽取
- ✅ 資訊查詢（新聞、維基）
- ✅ 搜尋任務（Wikipedia 等 train 任務）
- ✅ Held-out 任務見「泛化驗證」分頁（2/4 離線基線）
- ✅ 多步驟互動

**已知限制：**
- 🚫 無法繞過登入/CAPTCHA
- 🚫 PDF / 檔案下載型 URL
- 🚫 跨域 iFrame / Shadow DOM
- 🚫 **頁面摘要 / 改寫**（僅支援抽取頁面上已有文字，非生成式摘要）
- ⚠️ 同時只能執行一個任務（防 OOM）
- ⚠️ 複雜多步驟表單（不穩定）
- ⚠️ 重 JS SPA 可能逾時
- ⚠️ 地理限制內容
- ⚠️ 需要有效的 LLM API Key
""")

