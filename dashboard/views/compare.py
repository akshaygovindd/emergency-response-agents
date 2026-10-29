"""Compare page: the same run (scenario + seed) under two systems, side by side on one clock.

Everything shown is replayed from saved logs (no simulation, no API calls). Python builds both bundles
and the "first difference" note; the browser draws two maps and keeps one minute clock.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import streamlit as st

import common

from erc.dashboard.compare import SYSTEM_NAMES, first_difference
from erc.dashboard.export import export_replay
from erc.dashboard.player import assets_stamp, render_compare
from erc.dashboard.replay import MODE_ORDER, available_runs

SCENARIO_ORDER = ["normal", "surge", "bottleneck"]
DEFAULTS = {"version": "v1", "scenario": "normal", "run": 1, "a": "greedy", "b": "negotiation"}


@st.cache_data
def runs_index():
    return available_runs()


@st.cache_data(show_spinner=False)
def compare_html(version: str, scenario: str, seed: int, mode_a: str, mode_b: str, stamp: float) -> str:
    sides = []
    for mode in (mode_a, mode_b):
        sides.append({"label": SYSTEM_NAMES[mode] + f" ({version})", "bundle": export_replay(version, scenario, seed, mode)})
    logs = []
    for mode in (mode_a, mode_b):
        path = next(r.path for r in runs_index() if (r.version, r.scenario, r.seed, r.mode) == (version, scenario, seed, mode))
        logs.append([json.loads(line) for line in path.read_text().splitlines() if line])
    return render_compare(sides[0], sides[1], first_difference(logs[0], logs[1], SYSTEM_NAMES[mode_a], SYSTEM_NAMES[mode_b]))


def pick(col, label, options, preferred, key, format_func=str):
    index = options.index(preferred) if preferred in options else 0
    return col.selectbox(label, options, index=index, key=key, format_func=format_func)


common.setup()
st.markdown("<style>iframe{height:calc(100vh - 118px) !important;min-height:600px}</style>", unsafe_allow_html=True)
slot, (c_version, c_scenario, c_run, c_a, c_b) = common.header("Compare", (0.8, 1.0, 1.2, 1.2, 1.3))
runs = runs_index()
version = pick(c_version, "Version", sorted({r.version for r in runs}), DEFAULTS["version"], "cmp_version")
in_version = [r for r in runs if r.version == version]
scenario = pick(c_scenario, "Scenario", [s for s in SCENARIO_ORDER if any(r.scenario == s for r in in_version)],
                DEFAULTS["scenario"], "cmp_scenario")
in_scenario = [r for r in in_version if r.scenario == scenario]
number = pick(c_run, "Run", sorted({r.run_number for r in in_scenario}), DEFAULTS["run"], "cmp_run",
              lambda n: f"Run {n} (seed {n + 41})")
modes = [m for m in MODE_ORDER if any(r.mode == m and r.run_number == number for r in in_scenario)]
mode_a = pick(c_a, "Left system", modes, DEFAULTS["a"], "cmp_a", SYSTEM_NAMES.get)
mode_b = pick(c_b, "Right system", modes, DEFAULTS["b"], "cmp_b", SYSTEM_NAMES.get)
common.subtitle(slot, f"Compare &middot; {scenario.title()} scenario &middot; run {number} (seed {number + 41}) "
                      f"&middot; {version}")
st.iframe(compare_html(version, scenario, number + 41, mode_a, mode_b, assets_stamp()), height=900)
