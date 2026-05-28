"""Eval Dashboard — KPI cards, pass/fail visualization, detailed results."""

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
    '<h1 style="margin-bottom:0;">📊 Eval Dashboard</h1>',
    unsafe_allow_html=True,
)
st.caption("Automated evaluation results from SEC 10-K pipeline and Browser Agent tasks")

summary = _load_summary()
csv_files = sorted(_REPORTS.glob("eval*.csv"), reverse=True) if _REPORTS.exists() else []
if not csv_files and _REPORTS.exists():
    csv_files = sorted(_REPORTS.glob("latest.csv"), reverse=True)

if summary:
    # KPI Cards
    st.markdown("### Key Metrics")
    k1, k2, k3, k4 = st.columns(4)

    sec_ok = summary.get("sec_ok", 0)
    sec_total = summary.get("sec_filings", summary.get("sec_total", 1))
    agent_total = summary.get("agent_tasks", summary.get("agent_total", 1))
    agent_rate = summary.get("agent_success_rate", 0)
    agent_ok = int(agent_rate * agent_total) if agent_rate <= 1 else int(agent_rate)

    k1.metric(
        "SEC 10-K",
        f"{sec_ok}/{sec_total}",
        delta="All pass" if sec_ok == sec_total else f"{sec_total - sec_ok} failed",
        delta_color="normal" if sec_ok == sec_total else "inverse",
    )
    k2.metric(
        "Browser Agent",
        f"{agent_ok}/{agent_total}",
        delta=f"{agent_ok/max(agent_total,1):.0%} success",
    )
    k3.metric(
        "P50 Latency",
        f"{summary.get('agent_p50_latency_s', 'N/A')}s",
        help="Median task completion time",
    )
    k4.metric(
        "P50 Cost",
        f"${summary.get('agent_p50_cost_usd', 0):.4f}",
        help="Median LLM cost per task",
    )

    # Pass/Fail visual bar
    total_tasks = sec_total + agent_total
    total_pass = sec_ok + agent_ok
    col_bar, col_pct = st.columns([4, 1])
    with col_bar:
        st.progress(min(max(total_pass / max(total_tasks, 1), 0.0), 1.0))
    with col_pct:
        st.markdown(f"**{total_pass}/{total_tasks}** pass")

    st.divider()

    # Breakdown
    st.markdown("### Task Breakdown")
    col_sec, col_agent = st.columns(2)

    with col_sec:
        st.markdown("#### 📄 SEC 10-K Pipeline")
        if sec_ok == sec_total:
            st.success(f"All {sec_total} filings extracted successfully (Tier0, $0 LLM cost)")
        else:
            st.warning(f"{sec_ok}/{sec_total} filings OK")

    with col_agent:
        st.markdown("#### 🤖 Browser Agent")
        if agent_ok == agent_total:
            st.success(f"All {agent_total} tasks completed")
        else:
            st.info(
                f"{agent_ok}/{agent_total} tasks succeed. "
                f"Silent failures: {summary.get('agent_silent_failures', 0)}"
            )
else:
    st.warning("No eval summary found. Run evaluation scripts first.")

st.divider()

# Detailed CSV data
if csv_files:
    df = pd.read_csv(csv_files[0])
    st.markdown("### Detailed Results")
    st.caption(f"Source: `{csv_files[0].name}` — {len(df)} rows")

    task_filter = st.radio(
        "Filter by task type",
        ["All", "SEC 10-K", "Browser Agent"],
        horizontal=True,
    )
    if task_filter == "SEC 10-K":
        df = df[df["task"] == "sec_10k"]
    elif task_filter == "Browser Agent":
        df = df[df["task"] == "agent"]

    # Color-coded status
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

    # Agent extracted results
    if "extracted_result" in df.columns:
        agent_rows = df[df["task"] == "agent"]
        if not agent_rows.empty:
            st.markdown("### 🤖 Agent Extracted Results")
            for _, row in agent_rows.iterrows():
                result_text = str(row.get("extracted_result", ""))
                status = row.get("status", "")
                record = row.get("record_id", "")
                icon = "✅" if status == "success" else "❌"

                with st.expander(f"{icon} {record} — {status}", expanded=(status == "success")):
                    if result_text and result_text != "nan":
                        st.code(result_text, language=None)
                    else:
                        st.caption("No result extracted")
                    elapsed = row.get("elapsed_s", row.get("latency_s"))
                    if pd.notna(elapsed):
                        usd = row.get("usd_per_run", row.get("cost_usd", 0)) or 0
                        st.caption(f"⏱️ {float(elapsed):.1f}s | 💰 ${float(usd):.4f}")
else:
    st.warning(
        "No eval CSV found. Run:\n\n"
        "```bash\n"
        "python scripts/run_eval.py --split train\n"
        "python scripts/run_agent_eval.py\n"
        "```"
    )

# Raw summary JSON
if summary:
    with st.expander("📋 Raw Summary JSON"):
        st.json(summary)
