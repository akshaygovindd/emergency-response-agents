"""Emergency response dashboard: replay saved runs (no simulation, no API calls).

Run with:  streamlit run dashboard/app.py
Page: "Replay" (animated player). views/replay_simple.py (milestone-1 fallback) is kept but not in the menu.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

st.set_page_config(page_title="Emergency response replay", layout="wide", initial_sidebar_state="collapsed")
from common import BASE, PAGES

pages = [st.Page(path, title=label, default=(label == "Replay")) for label, path in PAGES if (BASE / path).exists()]
st.navigation(pages, position="hidden").run()
