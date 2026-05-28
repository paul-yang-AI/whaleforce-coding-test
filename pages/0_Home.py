"""首頁 — 專案概覽、架構卡片、即時健康指標。"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

_REPORTS = Path(__file__).resolve().parent.parent / "reports"


def _load_summary() -> dict | None:
    p = _REPORTS / "eval_summary.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


st.markdown(
    """
<style>
.hero-title { font-size: 2.6rem; font-weight: 900; margin-bottom: 0; letter-spacing: 0.03em; }
.hero-sub { font-size: 1.05rem; color: #555; margin-top: 0.3rem; line-height: 1.8; }
.arch-card {
    border: 1px solid #e0e0e0; border-radius: 14px; padding: 1.3rem;
    text-align: center; background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
    transition: box-shadow 0.2s;
}
.arch-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.arch-card h3 { margin: 0.5rem 0 0.3rem; font-size: 1.05rem; font-weight: 700; }
.arch-card p { margin: 0; font-size: 0.82rem; color: #555; line-height: 1.6; }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown('<p class="hero-title">🐋 Whaleforce AI 程式開發測驗</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="hero-sub">SEC 10-K 混合抽取管線 + LLM 瀏覽器自動化代理<br>'
    "Streamlit · Playwright · Gemini · SQLite</p>",
    unsafe_allow_html=True,
)

st.divider()

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(
        '<div class="arch-card">'
        "<h3>📄 SEC 10-K 管線</h3>"
        "<p>混合式 Tier0（BS4/正則）+ LLM 仲裁<br>"
        "三層 fallback · 合併偵測 · 跨引用過濾</p>"
        "</div>",
        unsafe_allow_html=True,
    )
with col2:
    st.markdown(
        '<div class="arch-card">'
        "<h3>🤖 瀏覽器代理</h3>"
        "<p>計畫→執行→觀察→驗證→反思<br>"
        "Playwright + LLM 規劃 + 分類式錯誤恢復</p>"
        "</div>",
        unsafe_allow_html=True,
    )
with col3:
    st.markdown(
        '<div class="arch-card">'
        "<h3>📊 評估駕馭層</h3>"
        "<p>L1 單元 / L2 整合 / L3 端對端<br>"
        "CSV 報告 · 成本追蹤 · 熔斷機制</p>"
        "</div>",
        unsafe_allow_html=True,
    )

st.divider()

summary = _load_summary()
if summary:
    st.subheader("即時評估指標")
    m1, m2, m3, m4 = st.columns(4)

    sec_pass = summary.get("sec_ok", 0)
    sec_total = summary.get("sec_filings", summary.get("sec_total", 1))
    agent_total = summary.get("agent_tasks", summary.get("agent_total", 1))
    agent_rate = summary.get("agent_success_rate", 0)
    agent_pass = int(agent_rate * agent_total) if agent_rate <= 1 else int(agent_rate)
    p50_lat = summary.get("agent_latency_p50", summary.get("agent_p50_latency_s"))
    p50_cost = summary.get("agent_usd_p50", summary.get("agent_p50_cost_usd", 0))

    m1.metric("SEC 10-K", f"{sec_pass}/{sec_total}", delta="全部通過" if sec_pass == sec_total else None)
    m2.metric("瀏覽器代理", f"{agent_pass}/{agent_total}", delta=f"{agent_rate:.0%}")
    m3.metric("P50 延遲", f"{p50_lat:.1f}s" if p50_lat else "N/A")
    m4.metric("P50 成本", f"${p50_cost:.4f}" if p50_cost else "N/A")

    overall = (sec_pass + agent_pass) / max(sec_total + agent_total, 1)
    st.progress(
        min(max(overall, 0.0), 1.0),
        text=f"整體通過率：{sec_pass + agent_pass}/{sec_total + agent_total} 項任務通過",
    )
else:
    st.info("尚無評估摘要。請先執行 `python scripts/run_eval.py --split train --write-summary`")

st.divider()

with st.expander("架構概覽", expanded=True):
    st.markdown("""
```
┌──────────────────────────────────────────────────────────┐
│                Streamlit 多頁面應用程式                      │
├──────────────┬──────────────────┬─────────────────────────┤
│  SEC 10-K    │  瀏覽器代理       │  評估儀表板               │
│  (頁面 1)    │  (頁面 2)        │  (頁面 3)                │
├──────────────┴──────────────────┴─────────────────────────┤
│                  shared_harness/                            │
│  llm_router · cost_tracker · job_store · edgar_client      │
│  llm_parse · prompt_loader · schemas                       │
├──────────────────────────────────────────────────────────┤
│  LLM 層：Gemini (主要) → OpenRouter (備援)                  │
│  預算：$20 全域 · $0.50/代理執行 · 熔斷器                     │
└──────────────────────────────────────────────────────────┘
```
""")

with st.expander("技術堆疊"):
    st.markdown("""
| 層級 | 技術 | 用途 |
|------|------|------|
| 前端 | Streamlit | 多頁面即時狀態應用 |
| 瀏覽器 | Playwright | 無頭 Chrome 自動化 |
| LLM | Gemini Flash/Pro | 規劃、驗證、仲裁 |
| 備援 | OpenRouter | Gemini 不可用時切換 |
| 儲存 | SQLite WAL | 任務紀錄、步驟、成本事件 |
| 解析 | BeautifulSoup4 | SEC HTML 正規化 |
| 部署 | Zeabur + Docker | 從 GitHub 自動部署 |
| 測試 | pytest (65+) | 單元 / 整合 / 端對端 |
""")

with st.expander("設計決策（面試重點）"):
    st.markdown("""
**為什麼用混合式 Tier0 + LLM，而非純 LLM？**
- 成本：Tier0（BS4/正則）以 $0 成本處理 90%+ 的 items
- 可靠性：確定性抽取不會幻覺出錯誤的段落邊界
- LLM 仲裁僅在爭議邊界啟動（< 5% 的案例）

**為什麼用 Plan-Act-Observe-Verify-Reflect 循環？**
- 結構化代理架構防止無限循環
- 分類式恢復（element_not_found → 捲動後重試, timeout → 延長等待）
- 每一步都可審計 — SQLite 完整追蹤

**為什麼選 Gemini + OpenRouter 備援？**
- Gemini Flash：速度最快、成本最低的 Tier1 規劃
- OpenRouter：模型多樣性，避免供應商鎖定
- 預算熔斷器防止失控成本

**Contract-Driven Evaluation（無需 Ground Truth）**
- Span integrity：`body[start:end] == text` → 零幻覺保證
- Token ratio ≥ 0.85 → 零摘要保證
- Header retention → 邊界精度保證
- 三者結合，不需人工標注即可驗證品質
""")
