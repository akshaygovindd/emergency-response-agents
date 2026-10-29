"""Compare page: the same run (scenario + seed) under two systems, side by side on one clock.

A full-window page with no Streamlit widgets. Python builds both runs and the first-difference card from the saved
logs (no simulation, no API calls); the run and the two systems are chosen in the page's run selector and applied
through the page address (?v=v1&s=normal&r=1&m1=greedy&m2=negotiation).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import streamlit as st

from erc.dashboard.catalog import resolve_selection, run_catalog
from erc.dashboard.compare import SYSTEM_NAMES, first_difference
from erc.dashboard.export import export_replay
from erc.dashboard.pages import FULL_WINDOW_CSS, page_stamp, render_page
from erc.dashboard.player import APP_DIR, app_stamp, render_replay_app
from erc.dashboard.replay import available_runs

PAGE_DIR = Path(__file__).resolve().parents[1] / "compare_app"


@st.cache_data
def runs_index():
    return available_runs()


@st.cache_data(show_spinner=False)
def page_html(version: str, scenario: str, run: str, left: str, right: str, stamp: float) -> str:
    runs = runs_index()
    catalog = run_catalog(runs)
    seed = int(run) + 41
    sides, logs = [], []
    for mode in (left, right):
        bundle = export_replay(version, scenario, seed, mode)
        path = next(r.path for r in runs if (r.version, r.scenario, r.seed, r.mode) == (version, scenario, seed, mode))
        logs.append([json.loads(line) for line in path.read_text().splitlines() if line])
        k = bundle["frames"][-1]["k"]
        sides.append({"label": SYSTEM_NAMES[mode], "html": render_replay_app(bundle, catalog, mode="compare"),
                      "last": bundle["meta"]["last_minute"], "conflicts": [{"t": c["t"], "plain": c["plain"]} for c in bundle["conflicts"]],
                      "sub": f"{k['crit_ok']} of {bundle['meta']['critical_total']} critical patients in time at the end",
                      "ticks": sorted({i["arrival_min"] for i in bundle["incidents"]})})
    diff = first_difference(logs[0], logs[1], SYSTEM_NAMES[left], SYSTEM_NAMES[right])
    card = None if diff is None else {"t": diff["t"], "left": diff["a_plain"], "right": diff["b_plain"]}
    return render_page(PAGE_DIR, {"catalog": catalog, "sel": {"v": version, "s": scenario, "r": run, "m1": left, "m2": right},
                                  "left": sides[0], "right": sides[1], "diff": card, "ticks": sides[0]["ticks"] + sides[1]["ticks"]})


st.markdown(FULL_WINDOW_CSS, unsafe_allow_html=True)
q = st.query_params
catalog = run_catalog(runs_index())
version, scenario, run, left = resolve_selection(catalog, q.get("v"), q.get("s"), q.get("r"), q.get("m1"), default=("v1", "normal", "1", "greedy"))
right = resolve_selection(catalog, version, scenario, run, q.get("m2"))[3]
st.iframe(page_html(version, scenario, run, left, right, max(page_stamp(PAGE_DIR), app_stamp())), height=900)
