"""What-if page: change ambulances, incidents and seed; run naive and greedy live; replay the result.

Generated in memory only: no scenario, log or result is saved, and no API is called. Agent systems are
shown disabled because they take minutes and use API calls (see the saved runs on the other pages).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import streamlit as st

import common

from erc.config import ScenarioName
from erc.dashboard.player import assets_stamp, render_player
from erc.dashboard.whatif import AMBULANCES, INCIDENTS, LIVE_SYSTEMS, run_whatif

PROFILES = {"normal": "Normal (12 incidents over 75 min)", "surge": "Surge mix (more severe victims)",
            "bottleneck": "Bottleneck (arrivals in 20 min, trauma half full)"}
DEFAULT = {"ambulances": 5, "incidents": 12, "seed": 42, "profile": "normal"}


@st.cache_data(show_spinner=False, max_entries=20)
def simulate(ambulances: int, incidents: int, seed: int, profile: str) -> dict:
    return run_whatif(ambulances, incidents, seed, ScenarioName(profile))


@st.cache_data(show_spinner=False, max_entries=20)
def player_html(ambulances: int, incidents: int, seed: int, profile: str, mode: str, stamp: float) -> str:
    return render_player(simulate(ambulances, incidents, seed, profile)[mode]["bundle"])


def pct(x):
    return "n/a" if x is None else f"{x:.0%}"


def result_card(mode: str, m: dict) -> str:
    crit = m["n_critical"] - m["critical_unserved"]
    return (f"<div class='wi-card'><div class='wi-sys'>{mode.title()}</div>"
            f"<div class='wi-big'>{pct(m['critical_service_rate'])}</div>"
            f"<div class='wi-note'>critical service rate &middot; {m['n_critical']} critical of {m['n_victims']} victims</div>"
            f"<div class='wi-note'>{pct(m['contacted_rate'])} reached &middot; {m['response_mean']:.1f} min average response</div></div>")


common.setup()
st.markdown("""<style>
iframe{height:calc(100vh - 118px) !important;min-height:600px}
.wi-card{background:#121b27;border:1px solid #243246;border-radius:12px;padding:8px 12px;margin-bottom:8px}
.wi-sys{font-size:.75rem;letter-spacing:.14em;text-transform:uppercase;color:#8a9bb0;font-weight:600}
.wi-big{font-size:1.9rem;font-weight:700;line-height:1.15;color:#dbe3ee}
.wi-note{font-size:.82rem;color:#8a9bb0}
.wi-off{font-size:.82rem;color:#8a9bb0;border:1px dashed #34465d;border-radius:8px;padding:6px 10px;margin-top:4px}
</style>""", unsafe_allow_html=True)
slot, _ = common.header("What-if")
common.subtitle(slot, "What-if &middot; generated live in memory &middot; nothing is saved, no API calls")

controls, view = st.columns([1, 4.3], gap="medium")
with controls:
    profile = st.selectbox("Base profile", list(PROFILES), format_func=PROFILES.get, key="wi_profile")
    ambulances = st.slider("Ambulances", *AMBULANCES, DEFAULT["ambulances"], key="wi_amb")
    incidents = st.slider("Incidents", *INCIDENTS, DEFAULT["incidents"], key="wi_inc")
    seed = st.number_input("Seed", min_value=0, max_value=9999, value=DEFAULT["seed"], step=1, key="wi_seed")
    if st.button("Run", type="primary", use_container_width=True):
        st.session_state["wi_applied"] = (int(ambulances), int(incidents), int(seed), profile)
    applied = st.session_state.get("wi_applied")
    if applied is None:
        st.markdown("<div class='wi-off'>Set the numbers and press <b>Run</b>. Naive and greedy run live in about a second.</div>",
                    unsafe_allow_html=True)
    else:
        results = simulate(*applied)
        st.radio("Replay system", list(LIVE_SYSTEMS), index=1, horizontal=True, format_func=str.title, key="wi_mode")
        for mode in LIVE_SYSTEMS:
            st.markdown(result_card(mode, results[mode]["metrics"]), unsafe_allow_html=True)
    st.markdown("<div class='wi-off'><b>Agents, Negotiation, Oracle</b> are disabled here: agent runs take minutes and "
                "use API calls. See the saved runs on the Replay, Compare and Results pages.</div>", unsafe_allow_html=True)
    agent_cols = st.columns(3)
    for col, name in zip(agent_cols, ("Agents", "Negotiation", "Oracle")):
        col.button(name, disabled=True, key=f"wi_off_{name}", use_container_width=True)

with view:
    if applied is None:
        st.info("The replay of your what-if appears here.")
    else:
        st.iframe(player_html(*applied, st.session_state.get("wi_mode", "greedy"), assets_stamp()), height=820)
