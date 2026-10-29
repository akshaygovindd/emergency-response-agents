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


def pick(label: str, options: list, preferred, key: str, format_func=str):
    index = options.index(preferred) if preferred in options else 0
    return st.sidebar.selectbox(label, options, index=index, key=key, format_func=format_func)


def select_run():
    """Version -> Scenario -> Run -> System, offering only runs whose logs exist."""
    runs = runs_index()
    st.sidebar.header("Run")
    version = pick("Version", sorted({r.version for r in runs}), DEFAULTS["version"], "pl_version")
    in_version = [r for r in runs if r.version == version]
    scenario = pick("Scenario", [s for s in SCENARIO_ORDER if any(r.scenario == s for r in in_version)],
                    DEFAULTS["scenario"], "pl_scenario")
    in_scenario = [r for r in in_version if r.scenario == scenario]
    number = pick("Run", sorted({r.run_number for r in in_scenario}), DEFAULTS["run"], "pl_run",
                  lambda n: f"Run {n} (seed {n + 41})")
    modes = [m for m in MODE_ORDER if any(r.mode == m and r.run_number == number for r in in_scenario)]
    mode = pick("System", modes, DEFAULTS["mode"], "pl_mode")
    return next(r for r in in_scenario if r.run_number == number and r.mode == mode)


st.markdown("<style>.block-container{padding-top:2.2rem;padding-bottom:0.5rem}</style>", unsafe_allow_html=True)
run = select_run()
st.iframe(player_html(run.version, run.scenario, run.seed, run.mode, assets_stamp()), height=PLAYER_HEIGHT)
