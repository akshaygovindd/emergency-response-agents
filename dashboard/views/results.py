"""Results page: the evidence from results/v1 and results/v2, one chart per question, always labelled by version.

A full-window page with no Streamlit widgets. Python computes the tables and the takeaway sentences from
results/<version>/runs.jsonl (read-only); the page draws them. Both versions are embedded and switched in the page.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import streamlit as st

from erc.dashboard import results_view as rv
from erc.dashboard.pages import FULL_WINDOW_CSS, page_stamp, render_page

PAGE_DIR = Path(__file__).resolve().parents[1] / "results_app"


@st.cache_data(show_spinner=False)
def page_html(initial: str, stamp: float) -> str:
    return render_page(PAGE_DIR, {"initial": initial, "versions": {v: rv.results_payload(v) for v in rv.FRAMES}})


st.markdown(FULL_WINDOW_CSS, unsafe_allow_html=True)
q = st.query_params
st.iframe(page_html(q.get("v") if q.get("v") in rv.FRAMES else "v1", page_stamp(PAGE_DIR, Path(__file__).resolve().parents[1] / "ui")), height=900)
