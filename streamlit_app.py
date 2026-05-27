"""Whaleforce Streamlit multi-page app."""

from shared_harness.env import load_env

load_env()

import streamlit as st

st.set_page_config(page_title="Whaleforce", page_icon="🐋", layout="wide")

home = st.Page("pages/0_Home.py", title="Home", default=True)
sec = st.Page("pages/1_SEC_10K.py", title="SEC 10K")
agent = st.Page("pages/2_Browser_Agent.py", title="Browser Agent")
eval_page = st.Page("pages/3_Eval.py", title="Eval")

pg = st.navigation([home, sec, agent, eval_page])
pg.run()
