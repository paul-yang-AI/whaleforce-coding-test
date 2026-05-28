"""評估儀表板 — KPI 卡片、通過/失敗視覺化、詳細結果。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

_REPORTS = Path(__file__).resolve().parent.parent / "reports"


def _load_summary() -> dict | None:
    p = _REPORTS / "eval_summary.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


st.markdown(
    '<h1 style="margin-bottom:0;">📊 評估儀表板</h1>',
    unsafe_allow_html=True,
)
st.caption("SEC 10-K 管線與瀏覽器代理的自動化評估結果")

summary = _load_summary()
csv_files = sorted(_REPORTS.glob("eval*.csv"), reverse=True) if _REPORTS.exists() else []
if not csv_files and _REPORTS.exists():
    csv_files = sorted(_REPORTS.glob("latest.csv"), reverse=True)

if summary:
    st.markdown("### 關鍵指標")
    k1, k2, k3, k4 = st.columns(4)

    sec_ok = summary.get("sec_ok", 0)
    sec_total = summary.get("sec_filings", summary.get("sec_total", 1))
    agent_total = summary.get("agent_tasks", summary.get("agent_total", 1))
    agent_rate = summary.get("agent_success_rate", 0)
    agent_ok = int(agent_rate * agent_total) if agent_rate <= 1 else int(agent_rate)

    k1.metric(
        "SEC 10-K",
        f"{sec_ok}/{sec_total}",
        delta="全部通過" if sec_ok == sec_total else f"{sec_total - sec_ok} 項失敗",
        delta_color="normal" if sec_ok == sec_total else "inverse",
    )
    k2.metric(
        "瀏覽器代理",
        f"{agent_ok}/{agent_total}",
        delta=f"{agent_ok/max(agent_total,1):.0%} 成功",
    )
    k3.metric(
        "P50 延遲",
        f"{summary.get('agent_p50_latency_s', 'N/A')}s",
        help="中位數任務完成時間",
    )
    k4.metric(
        "P50 成本",
        f"${summary.get('agent_p50_cost_usd', 0):.4f}",
        help="中位數每任務 LLM 成本",
    )

    total_tasks = sec_total + agent_total
    total_pass = sec_ok + agent_ok
    col_bar, col_pct = st.columns([4, 1])
    with col_bar:
        st.progress(min(max(total_pass / max(total_tasks, 1), 0.0), 1.0))
    with col_pct:
        st.markdown(f"**{total_pass}/{total_tasks}** 通過")

    st.divider()

    st.markdown("### 任務細項")
    col_sec, col_agent = st.columns(2)

    with col_sec:
        st.markdown("#### 📄 SEC 10-K 管線")
        if sec_ok == sec_total:
            st.success(f"全部 {sec_total} 份報表成功抽取（Tier0，$0 LLM 成本）")
        else:
            st.warning(f"{sec_ok}/{sec_total} 份報表通過")

    with col_agent:
        st.markdown("#### 🤖 瀏覽器代理")
        if agent_ok == agent_total:
            st.success(f"全部 {agent_total} 項任務完成")
        else:
            st.info(
                f"{agent_ok}/{agent_total} 項任務成功。"
                f"靜默失敗：{summary.get('agent_silent_failures', 0)}"
            )
else:
    st.warning("尚未找到評估摘要，請先執行評估腳本。")

st.divider()

if csv_files:
    df = pd.read_csv(csv_files[0])
    st.markdown("### 詳細結果")
    st.caption(f"資料來源：`{csv_files[0].name}` — {len(df)} 筆")

    task_filter = st.radio(
        "依任務類型篩選",
        ["全部", "SEC 10-K", "瀏覽器代理"],
        horizontal=True,
    )
    if task_filter == "SEC 10-K":
        df = df[df["task"] == "sec_10k"]
    elif task_filter == "瀏覽器代理":
        df = df[df["task"] == "agent"]

    def _highlight_status(row):
        if row.get("status") == "success" or row.get("status") == "ok":
            return ["background-color: #dcfce7"] * len(row)
        elif row.get("status") == "failed":
            return ["background-color: #fee2e2"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df.style.apply(_highlight_status, axis=1),
        use_container_width=True,
        height=min(400, 35 * len(df) + 38),
    )

    if "extracted_result" in df.columns:
        agent_rows = df[df["task"] == "agent"]
        if not agent_rows.empty:
            st.markdown("### 🤖 代理抽取結果")
            for _, row in agent_rows.iterrows():
                result_text = str(row.get("extracted_result", ""))
                status = row.get("status", "")
                record = row.get("record_id", "")
                icon = "✅" if status == "success" else "❌"

                with st.expander(f"{icon} {record} — {status}", expanded=(status == "success")):
                    if result_text and result_text != "nan":
                        st.code(result_text, language=None)
                    else:
                        st.caption("未抽取到結果")
                    elapsed = row.get("elapsed_s", row.get("latency_s"))
                    if pd.notna(elapsed):
                        usd = row.get("usd_per_run", row.get("cost_usd", 0)) or 0
                        st.caption(f"⏱️ {float(elapsed):.1f}s | 💰 ${float(usd):.4f}")
else:
    st.warning(
        "尚未找到評估 CSV。請執行：\n\n"
        "```bash\n"
        "python scripts/run_eval.py --split train\n"
        "python scripts/run_agent_eval.py\n"
        "```"
    )

if summary:
    with st.expander("📋 原始摘要 JSON"):
        st.json(summary)
