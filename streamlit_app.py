"""Whaleforce Streamlit multi-page app."""

from shared_harness.env import load_env

load_env()

import os

import streamlit as st

st.set_page_config(page_title="Whaleforce AI", page_icon="🐋", layout="wide")

st.markdown(
    """<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;500;700;900&display=swap');
    html, body, [class*="css"] { font-family: 'Noto Sans TC', 'Microsoft JhengHei', sans-serif; }
    h1, h2, h3, h4, h5, h6 { font-family: 'Noto Sans TC', 'Microsoft JhengHei', sans-serif; font-weight: 700; letter-spacing: 0.02em; }
    p, span, div, li { line-height: 1.7; }
    .stMetric label { font-size: 0.85rem !important; }
    </style>""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown(
        '<p style="font-size:1.6rem; font-weight:900; margin:0;">🐋 Whaleforce</p>'
        '<p style="font-size:0.85rem; color:#666; margin:0;">AI 程式開發測驗</p>',
        unsafe_allow_html=True,
    )
    st.divider()

    st.markdown("**環境狀態**")
    _checks = {
        "GEMINI_API_KEY": bool(os.environ.get("GEMINI_API_KEY")),
        "OPENROUTER_API_KEY": bool(os.environ.get("OPENROUTER_API_KEY")),
        "SEC_USER_AGENT": bool(os.environ.get("SEC_USER_AGENT")),
    }
    for key, ok in _checks.items():
        icon = "✅" if ok else "❌"
        st.markdown(f"{icon} `{key}`")

    fallback_on = os.environ.get("LLM_FALLBACK_ENABLED", "true").lower() in ("1", "true")
    st.markdown(f"{'🔄' if fallback_on else '⏸️'} 備援模型：{'啟用' if fallback_on else '停用'}")

    st.divider()
    st.caption("Streamlit · Playwright · Gemini · SQLite")

home = st.Page("pages/0_Home.py", title="首頁", icon="🏠", default=True)
sec = st.Page("pages/1_SEC_10K.py", title="SEC 10-K 抽取", icon="📄")
agent = st.Page("pages/2_Browser_Agent.py", title="瀏覽器代理", icon="🤖")
eval_page = st.Page("pages/3_Eval.py", title="評估儀表板", icon="📊")

pg = st.navigation([home, sec, agent, eval_page])
pg.run()
