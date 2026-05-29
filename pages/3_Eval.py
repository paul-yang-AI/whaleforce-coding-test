"""評估儀表板 — 基準評估（train split）、已知限制、即時執行紀錄。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from shared_harness import job_store
from shared_harness.eval_ui import kpi_row_html

_REPORTS = Path(__file__).resolve().parent.parent / "reports"

_SEC_CARD_COLS = [
    "record_id",
    "domain",
    "required_items_found",
    "required_items_total",
    "token_ratio_p50",
    "char_coverage",
    "failure_category",
]
_AGENT_CARD_COLS = [
    "record_id",
    "domain",
    "task_type",
    "status",
    "steps",
    "elapsed_s",
    "llm_calls",
    "usd_per_run",
    "failure_category",
]


def _load_persisted_eval() -> tuple[dict | None, pd.DataFrame | None]:
    summary_path = _REPORTS / "eval_summary.json"
    csv_path = _REPORTS / "eval_train.csv"
    summary = None
    df = None
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            pass
    return summary, df


def _load_archived_eval() -> bool:
    """Load persisted eval summary/CSV into session state on demand. Returns True if found."""
    summary, df = _load_persisted_eval()
    found = False
    if summary:
        st.session_state["eval_summary"] = summary
        found = True
    if df is not None:
        st.session_state["eval_df"] = df
        found = True
    return found


def _run_benchmark(*, include_agent: bool) -> None:
    from shared_harness.eval_runner import (
        run_agent_eval,
        run_sec_eval,
        summarize_eval,
        write_eval_csv,
    )

    sec_results = run_sec_eval(split="train", use_arbiter=True)
    if include_agent:
        agent_results = run_agent_eval(split="train")
        all_results = [*sec_results, *agent_results]
    else:
        all_results = sec_results
    summary = summarize_eval(all_results)
    csv_path = _REPORTS / "eval_train.csv"
    write_eval_csv(all_results, csv_path)
    write_eval_csv(all_results, _REPORTS / "latest.csv")
    (_REPORTS / "eval_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    st.session_state["eval_summary"] = summary
    st.session_state["eval_df"] = pd.read_csv(csv_path)


def _status_icon(status: str) -> str:
    if status in ("success", "ok"):
        return "✅"
    if status in ("failed", "blocked"):
        return "❌"
    if status in ("running", "queued"):
        return "⏳"
    return "▪️"


def _render_sec_cards(df: pd.DataFrame) -> None:
    sec_df = df[df["task"] == "sec_10k"]
    if sec_df.empty:
        st.info("尚無 SEC 基準結果。請執行評估。")
        return
    for _, row in sec_df.iterrows():
        ticker = row.get("domain") or row.get("record_id", "")
        cat = row.get("failure_category", "")
        icon = _status_icon("ok" if cat == "ok" else "failed")
        req = f"{int(row.get('required_items_found', 0))}/{int(row.get('required_items_total', 0))}"
        ratio = row.get("token_ratio_p50", "")
        cov = row.get("char_coverage", "")
        st.markdown(
            f"{icon} **{ticker}** · `{row.get('record_id', '')}`  \n"
            f"Required items **{req}** · token ratio **{ratio}** · coverage **{cov}** · _{cat}_"
        )


def _render_agent_cards(df: pd.DataFrame) -> None:
    agent_df = df[df["task"] == "agent"]
    if agent_df.empty:
        st.info("尚無 Agent 基準結果。請執行完整評估。")
        return
    for _, row in agent_df.iterrows():
        tid = row.get("record_id", "")
        status = str(row.get("status", ""))
        icon = _status_icon(status)
        steps = row.get("steps", "")
        elapsed = row.get("elapsed_s", "")
        usd = row.get("usd_per_run", 0) or 0
        cat = row.get("failure_category", "")
        preview = str(row.get("extracted_result", "") or "")[:100]
        st.markdown(
            f"{icon} **{tid}** ({row.get('domain', '')}) — **{status}**  \n"
            f"Steps **{steps}** · **{float(elapsed):.1f}s** · **${float(usd):.4f}** · _{cat}_"
        )
        if preview and preview != "nan":
            st.caption(f"結果：{preview}{'…' if len(preview) >= 100 else ''}")


def _render_live_runs() -> None:
    st.markdown(
        "此區顯示 **瀏覽器代理** 與 **SEC 自訂抽取** 的即時執行紀錄（SQLite），"
        "供除錯與檢查失敗案例。**不計入** 上方基準 KPI。"
    )
    live_filter = st.radio("篩選", ["全部", "Agent", "SEC"], horizontal=True, key="live_run_filter")
    runs = job_store.list_recent_runs(limit=25)
    if live_filter == "Agent":
        runs = [r for r in runs if r.get("task_type") == "agent"]
    elif live_filter == "SEC":
        runs = [r for r in runs if r.get("task_type") == "sec"]

    if not runs:
        st.info("尚無執行紀錄。請至「瀏覽器代理」或「SEC 10K」頁提交任務。")
        return

    type_labels = {"agent": "🤖 Agent", "sec": "📄 SEC"}

    for run in runs:
        rid = run["id"]
        status = run.get("status", "")
        icon = _status_icon(status)
        short_id = rid[:8]
        task_type = run.get("task_type") or "?"
        type_badge = type_labels.get(task_type, task_type)
        usd = float(run.get("usd_total") or 0)
        steps = int(run.get("step_count") or 0)
        llm = int(run.get("llm_calls") or 0)
        created = (run.get("created_at") or "")[:19].replace("T", " ")

        title = (run.get("label") or "").strip()
        if not title:
            for step in job_store.get_run_steps(rid):
                log_raw = step.get("log_json")
                if not log_raw:
                    continue
                try:
                    log = json.loads(log_raw)
                except Exception:
                    continue
                if log.get("task"):
                    title = str(log["task"])[:100]
                    break
                if log.get("accession"):
                    title = f"SEC {log.get('ticker') or log['accession']}"
                    break
        if not title:
            title = "（無標題）"

        with st.expander(
            f"{icon} {type_badge} · **{title}** · "
            f"`{short_id}` · {status} · {created} · {steps} steps · ${usd:.4f}"
        ):
            st.caption(f"Run ID: `{rid}`")
            step_rows = job_store.get_run_steps(rid)
            if not step_rows:
                st.caption("（無步驟紀錄）")
            for s in step_rows:
                action = s.get("action") or "—"
                st_status = s.get("status") or ""
                st.markdown(f"- Step {s.get('step_index')}: `{action}` — {st_status}")
                log_raw = s.get("log_json")
                if log_raw:
                    try:
                        log = json.loads(log_raw)
                        if task_type == "sec":
                            summary_bits = []
                            if log.get("ticker"):
                                summary_bits.append(f"**{log['ticker']}**")
                            if log.get("accession"):
                                summary_bits.append(f"`{log['accession']}`")
                            if log.get("extracted") is not None:
                                summary_bits.append(
                                    f"已抽取 {log['extracted']} · 缺失 {log.get('missing', 0)} · "
                                    f"合併引用 {log.get('incorporated', 0)}"
                                )
                            if summary_bits:
                                st.caption(" · ".join(summary_bits))
                        if log.get("extracted_result"):
                            st.code(str(log["extracted_result"])[:500], language=None)
                        if log.get("error"):
                            st.error(str(log["error"]))
                    except Exception:
                        pass
            st.caption(f"LLM calls: {llm} · 成本: ${usd:.4f}")


# --- Page ---

st.markdown(
    '<h1 style="margin-bottom:0;">📊 評估儀表板</h1>',
    unsafe_allow_html=True,
)
st.caption(
    "**基準評估（Train Split）**：可重現的 evaluation set，供回歸測試與對外報告。"
    " **即時紀錄**：使用者自訂任務的可觀測性，非 benchmark KPI。"
)

col_load, col_run_sec, col_run_agent = st.columns(3)
with col_load:
    load_archived = st.button(
        "📂 載入存檔結果",
        type="primary",
        use_container_width=True,
        help="顯示已提交的 submission 基準結果（reports/，不重跑）",
    )
with col_run_sec:
    run_sec = st.button(
        "📄 重跑 SEC 基準（train）",
        type="secondary",
        use_container_width=True,
        help="manifest.json train 報表，約 1 分鐘",
    )
with col_run_agent:
    run_agent = st.button(
        "🤖 重跑完整基準（SEC + Agent）",
        type="secondary",
        use_container_width=True,
        help="含 Playwright + LLM，約 3–8 分鐘",
    )

if load_archived:
    if _load_archived_eval():
        st.success("✅ 已載入存檔基準結果")
    else:
        st.warning("找不到 `reports/eval_summary.json`，請改按重跑。")

if run_sec:
    with st.spinner("正在執行 SEC train 基準…"):
        try:
            _run_benchmark(include_agent=False)
            st.success("✅ SEC 基準完成")
        except Exception as exc:
            st.error(f"❌ 失敗：{exc}")

if run_agent:
    with st.spinner("正在執行 SEC + Agent train 基準…"):
        try:
            _run_benchmark(include_agent=True)
            st.success("✅ 完整基準完成")
        except Exception as exc:
            st.error(f"❌ 失敗：{exc}")

st.divider()

tab_bench, tab_limits, tab_live = st.tabs(
    ["📈 基準評估 Train", "⚠️ 已知限制", "🔴 即時執行紀錄"]
)

summary = st.session_state.get("eval_summary")
df = st.session_state.get("eval_df")

with tab_bench:
    if not summary:
        st.info("尚無基準結果。請按上方「📂 載入存檔結果」顯示 submission 基準，或按「重跑」執行新一輪。")
    else:
        st.markdown(kpi_row_html(summary), unsafe_allow_html=True)

        st.caption(
            "Held-out 任務（如 DuckDuckGo、BRK.B）不在此 KPI 內；"
            "詳見「已知限制」與 docs/analysis.md。"
        )

        if df is None or df.empty:
            st.warning(
                "基準摘要已載入，但找不到 `reports/eval_train.csv`。"
                "請按上方按鈕重新執行基準，或確認部署包含 reports 目錄。"
            )
        elif df is not None and not df.empty:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 📄 SEC 10-K（train manifest）")
                _render_sec_cards(df)
            with c2:
                st.markdown("#### 🤖 Browser Agent（train tasks.yaml）")
                _render_agent_cards(df)

            with st.expander("📥 下載完整 CSV（審查用）"):
                st.dataframe(df, use_container_width=True, height=320)
                st.download_button(
                    "下載 eval_train.csv",
                    df.to_csv(index=False).encode("utf-8"),
                    file_name="eval_train.csv",
                    mime="text/csv",
                )
            with st.expander("📋 eval_summary.json"):
                st.json(summary)

with tab_limits:
    st.markdown("""
### 設計說明

| 類型 | 用途 | 資料來源 |
|------|------|----------|
| **基準評估** | 可重現 KPI、submission 報告 | `tasks.yaml` / `manifest.json` train split |
| **即時紀錄** | 使用者自訂任務除錯 | SQLite `job_store`（Agent + SEC 抽取頁） |
| **Held-out** | 使用者自行驗證 generalization | 不在 train KPI 內 |

### Browser Agent — 穩定 / 不穩定

| 狀態 | 範例 |
|------|------|
| ✅ Train 通過 | example.com、httpbin extract、Wikipedia search、HN、GitHub |
| ⚠️ Held-out / demo | DuckDuckGo search（headless flaky，UI 可試但不計 KPI） |
| ⚠️ 不建議 demo | **Google 搜尋**（consent/動態 DOM → type 迴圈；agent 會 stuck 偵測後 fail） |
| 🚫 不支援 | 登入/CAPTCHA、PDF URL、iframe/shadow DOM、**生成式摘要**（僅抽取頁面文字） |
| ⚠️ 基礎設施 | Gemini 503 → `plan_failed`（已加 infra 重試） |
| 🔧 語意修復 | 搜尋任務若 planner 漏填 `value`，harness 從任務文字抽 query 並 role-first 輸入 |

### SEC 10-K — 穩定 / 困難

| 狀態 | 範例 |
|------|------|
| ✅ 良好 | MSFT、INTC（標準 TOC） |
| ⚠️ 困難 | Citi（大量 incorporated by reference）、iXBRL 複雜 |
| 🔍 搜尋 | 建議 **ticker**（GOOGL）或 accession；`google` 等單字易 EFTS 雜訊 |
| 📊 展示 | 結構化文字閱讀視圖；SEC viewer deep link（原文連結） |
| 🚫 未支援 | PDF-only 報表、非英文 20-F |

完整分析見 [docs/analysis.md](../docs/analysis.md) 與 README Known Limitations。
    """)

with tab_live:
    _render_live_runs()
