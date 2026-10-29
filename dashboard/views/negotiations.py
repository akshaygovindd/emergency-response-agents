"""Negotiations page: every conflict and hospital-admission negotiation of one saved run.

A full-window page with no Streamlit widgets: cards on the left, the steps of the chosen negotiation on the right,
raw log messages in collapsible code panels. Read-only (built from the event log; no simulation, no API calls).
The run is chosen in the page's run selector and applied through the page address (?v=v2&s=normal&r=1&m=negotiation).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import streamlit as st

from erc.dashboard.catalog import resolve_selection, run_catalog
from erc.dashboard.negotiations import is_notable, negotiation_records
from erc.dashboard.pages import FULL_WINDOW_CSS, page_stamp, render_page
from erc.dashboard.replay import available_runs

PAGE_DIR = Path(__file__).resolve().parents[1] / "negotiations_app"


@st.cache_data
def runs_index():
    return available_runs()


@st.cache_data(show_spinner=False)
def page_html(version: str, scenario: str, run: str, mode: str, stamp: float) -> str:
    runs = runs_index()
    path = next(r.path for r in runs if (r.version, r.scenario, r.run_number, r.mode) == (version, scenario, int(run), mode))
    records = negotiation_records([json.loads(line) for line in path.read_text().splitlines() if line])
    for r in records:
        r["notable"] = is_notable(r)
    return render_page(PAGE_DIR, {"catalog": run_catalog(runs), "sel": {"v": version, "s": scenario, "r": run, "m": mode}, "records": records})


st.markdown(FULL_WINDOW_CSS, unsafe_allow_html=True)
q = st.query_params
version, scenario, run, mode = resolve_selection(run_catalog(runs_index()), q.get("v"), q.get("s"), q.get("r"), q.get("m"),
                                                 default=("v2", "normal", "1", "negotiation"))
st.iframe(page_html(version, scenario, run, mode, page_stamp(PAGE_DIR)), height=900)
