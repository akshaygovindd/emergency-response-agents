"""Replay page: the animated player. Python builds the bundle from the run's log; the browser plays it.

Selecting a run reruns this script once and loads a new bundle into the player. Playing, pausing, speed
and the scrubber all happen inside the player (JavaScript), so they never trigger a Streamlit rerun.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import streamlit as st

from erc.dashboard.export import export_replay
from erc.dashboard.player import assets_stamp, render_player
from erc.dashboard.replay import MODE_ORDER, available_runs

SCENARIO_ORDER = ["normal", "surge", "bottleneck"]
PLAYER_HEIGHT = 920
DEFAULTS = {"version": "v1", "scenario": "normal", "run": 1, "mode": "negotiation"}


@st.cache_data
def runs_index():
    return available_runs()


@st.cache_data(show_spinner=False)
def player_html(version: str, scenario: str, seed: int, mode: str, stamp: float) -> str:
    return render_player(export_replay(version, scenario, seed, mode))


def pick(col, label: str, options: list, preferred, key: str, format_func=str):
    index = options.index(preferred) if preferred in options else 0
    return col.selectbox(label, options, index=index, key=key, format_func=format_func)


def select_run():
    """Top bar: title and run info on the left, then Version -> Scenario -> Run -> System (only runs with logs)."""
    runs = runs_index()
    title, c_version, c_scenario, c_run, c_mode = st.columns([3.2, 1, 1.2, 1.4, 1.5], vertical_alignment="bottom")
    version = pick(c_version, "Version", sorted({r.version for r in runs}), DEFAULTS["version"], "pl_version")
    in_version = [r for r in runs if r.version == version]
    scenario = pick(c_scenario, "Scenario", [s for s in SCENARIO_ORDER if any(r.scenario == s for r in in_version)],
                    DEFAULTS["scenario"], "pl_scenario")
    in_scenario = [r for r in in_version if r.scenario == scenario]
    number = pick(c_run, "Run", sorted({r.run_number for r in in_scenario}), DEFAULTS["run"], "pl_run",
                  lambda n: f"Run {n} (seed {n + 41})")
    modes = [m for m in MODE_ORDER if any(r.mode == m and r.run_number == number for r in in_scenario)]
    mode = pick(c_mode, "System", modes, DEFAULTS["mode"], "pl_mode")
    run = next(r for r in in_scenario if r.run_number == number and r.mode == mode)
    title.markdown(f"<div class='cc-title'>Emergency Response Command Center</div>"
                   f"<div class='cc-sub'>{run.scenario.title()} scenario &middot; run {run.run_number} (seed {run.seed}) "
                   f"&middot; {run.mode} system &middot; {run.version}</div>", unsafe_allow_html=True)
    return run


st.markdown("""<style>
header[data-testid="stHeader"],[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"]{display:none}
.block-container{padding:0.6rem 1rem 0 1rem;max-width:100%}
.cc-title{font-size:1.7rem;font-weight:700;line-height:1.15;color:#dbe3ee}
.cc-sub{font-size:0.95rem;color:#8a9bb0;margin-top:2px}
div[data-testid="stSelectbox"] label p{font-size:0.75rem;color:#8a9bb0}
iframe{height:calc(100vh - 118px) !important;min-height:600px}
</style>""", unsafe_allow_html=True)
run = select_run()
st.iframe(player_html(run.version, run.scenario, run.seed, run.mode, assets_stamp()), height=PLAYER_HEIGHT)
