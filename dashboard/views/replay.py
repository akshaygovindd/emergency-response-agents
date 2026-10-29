"""Replay page: the full-window replay app. Python builds the bundle from the run's log; the browser plays it.

The page has no Streamlit widgets: the run is chosen inside the app (run selector pill) and applied through the
page address (?v=v1&s=normal&r=1&m=negotiation). Playing, pausing, speed and the scrubber all happen in the browser,
so they never trigger a Streamlit rerun.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import streamlit as st

from erc.dashboard.catalog import resolve_selection, run_catalog
from erc.dashboard.export import export_replay
from erc.dashboard.player import app_stamp, render_replay_app
from erc.dashboard.replay import available_runs

FULL_WINDOW = """<style>
header[data-testid="stHeader"],[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],[data-testid="stStatusWidget"],
[data-testid="stToolbar"],[data-testid="stDecoration"],footer{display:none !important}
.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:#0A0E17}
.block-container{padding:0 !important;max-width:100% !important}
iframe{position:fixed;inset:0;width:100vw !important;height:100vh !important;border:0;z-index:5}
</style>"""


@st.cache_data
def catalog():
    return run_catalog(available_runs())


@st.cache_data(show_spinner=False)
def app_html(version: str, scenario: str, seed: int, mode: str, stamp: float) -> str:
    return render_replay_app(export_replay(version, scenario, seed, mode), catalog())


st.markdown(FULL_WINDOW, unsafe_allow_html=True)
q = st.query_params
version, scenario, run, mode = resolve_selection(catalog(), q.get("v"), q.get("s"), q.get("r"), q.get("m"))
st.iframe(app_html(version, scenario, int(run) + 41, mode, app_stamp()), height=900)
