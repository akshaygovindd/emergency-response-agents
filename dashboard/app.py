"""Emergency response dashboard: replay saved runs (no simulation, no API calls).

Run with:  streamlit run dashboard/app.py
Pages: "Replay" (animated player) and "Replay (simple)" (the milestone-1 fallback).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import streamlit as st

st.set_page_config(page_title="Emergency response replay", layout="wide", initial_sidebar_state="collapsed")
pages = [
    st.Page("views/replay.py", title="Replay", icon="🚑", default=True),
    st.Page("views/replay_simple.py", title="Replay (simple)", icon="🗺️"),
]
st.navigation(pages).run()
