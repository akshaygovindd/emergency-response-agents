"""What-if page: change ambulances, incidents, seed and profile; run naive and greedy live; replay the result.

A full-window page with no Streamlit widgets. The scenario is generated in memory and nothing is saved; no API is called.
Agent systems are shown disabled. The numbers are chosen on the page and applied through its address
(?amb=5&inc=12&seed=42&p=normal); Python runs the two baselines and the page shows both results and the replay.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import streamlit as st

from erc.dashboard.pages import FULL_WINDOW_CSS, page_stamp, render_page
from erc.dashboard.player import app_stamp, render_replay_app
from erc.dashboard.whatif import AMBULANCES, INCIDENTS, LIVE_SYSTEMS, PROFILES, difference_points, parse_params, run_whatif, summarize_run

PAGE_DIR = Path(__file__).resolve().parents[1] / "whatif_app"


@st.cache_data(show_spinner=False, max_entries=24)
def page_html(amb: int, inc: int, seed: int, profile: str, stamp: float) -> str:
    from erc.config import ScenarioName
    runs = run_whatif(amb, inc, seed, ScenarioName(profile))
    results = {m: {"summary": summarize_run(runs[m]["metrics"]), "html": render_replay_app(runs[m]["bundle"], {}, mode="inline")} for m in LIVE_SYSTEMS}
    return render_page(PAGE_DIR, {"params": {"amb": amb, "inc": inc, "seed": seed, "profile": profile}, "limits": {"amb": list(AMBULANCES), "inc": list(INCIDENTS)},
                                  "profiles": PROFILES, "results": results, "delta": difference_points({m: results[m]["summary"] for m in LIVE_SYSTEMS})})


st.markdown(FULL_WINDOW_CSS, unsafe_allow_html=True)
q = st.query_params
amb, inc, seed, profile = parse_params(q.get("amb"), q.get("inc"), q.get("seed"), q.get("p"))
st.iframe(page_html(amb, inc, seed, profile.value, max(page_stamp(PAGE_DIR, Path(__file__).resolve().parents[1] / "ui"), app_stamp())), height=900)
