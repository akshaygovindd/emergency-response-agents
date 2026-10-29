"""Emergency response dashboard: replay saved runs (no simulation, no API calls).

Run with:  streamlit run dashboard/app.py
Page: "Replay" (animated player). views/replay_simple.py (milestone-1 fallback) is kept but not in the menu.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import streamlit as st

st.set_page_config(page_title="Emergency response replay", layout="wide", initial_sidebar_state="collapsed")
pages = [
    st.Page("views/replay.py", title="Replay", icon="🚑", default=True),
]
st.navigation(pages, position="hidden").run()
