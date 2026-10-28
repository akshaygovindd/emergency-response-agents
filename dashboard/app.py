"""Replay dashboard: pick a saved run, press play, watch it unfold. Reads logs only (no API calls).

Run with:  streamlit run dashboard/app.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import plotly.graph_objects as go
import streamlit as st

from erc.dashboard.feed import CATEGORIES, feed_items
from erc.dashboard.replay import MODE_ORDER, Frame, Replay, available_runs

SEVERITY_COLORS = {"immediate": "#d62728", "delayed": "#e6b800", "minor": "#2ca02c", "done": "#b0b0b0"}
UNRESOLVED = ("waiting", "in_transport")
STEP_SECONDS = 0.35


@st.cache_data
def runs_index():
    return available_runs()


@st.cache_resource
def load_replay(path: str, scenario: str, seed: int, mode: str):
    run = next(r for r in runs_index() if r.path == Path(path))
    return Replay.load(run)


def triage(severity: int) -> str:
    return "immediate" if severity >= 4 else "delayed" if severity == 3 else "minor"


def incident_color(incident: dict) -> str:
    open_sev = [v["severity"] for v in incident["victims"] if v["status"] in UNRESOLVED]
    return SEVERITY_COLORS[triage(max(open_sev))] if open_sev else SEVERITY_COLORS["done"]


def build_map(frame: Frame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[h["x"] for h in frame.hospitals], y=[h["y"] for h in frame.hospitals],
        mode="markers+text", text=[h["id"] for h in frame.hospitals], textposition="top center",
        marker=dict(symbol="square", size=22, color="#1f77b4"), name="Hospitals", hoverinfo="text",
        hovertext=[f"{h['id']}: ER {h['er_occupied']}/{h['er_capacity']}" for h in frame.hospitals]))
    fig.add_trace(go.Scatter(
        x=[i["x"] for i in frame.incidents], y=[i["y"] for i in frame.incidents],
        mode="markers+text", text=[i["id"] for i in frame.incidents], textposition="bottom center",
        marker=dict(symbol="circle", size=16, color=[incident_color(i) for i in frame.incidents],
                    line=dict(width=1, color="#333")),
        name="Incidents", hoverinfo="text",
        hovertext=["<br>".join([i["id"]] + [f"{v['id']}: severity {v['severity']}, {v['status']}"
                                            for v in i["victims"]]) for i in frame.incidents]))
    fig.add_trace(go.Scatter(
        x=[a["x"] for a in frame.ambulances], y=[a["y"] for a in frame.ambulances],
        mode="markers+text", text=[a["id"] for a in frame.ambulances], textposition="top center",
        marker=dict(symbol="diamond", size=14, color=["#7f7f7f" if a["status"] == "available" else "#ff7f0e"
                                                      for a in frame.ambulances]),
        name="Ambulances", hoverinfo="text",
        hovertext=[f"{a['id']}: {a['status']} → {a['target']}, onboard {len(a['onboard'])}"
                   for a in frame.ambulances]))
    fig.add_trace(go.Scatter(
        x=[r["x"] for r in frame.responders], y=[r["y"] for r in frame.responders],
        mode="markers", marker=dict(symbol="triangle-up", size=11, color="#9467bd"), name="Responders",
        hoverinfo="text", hovertext=[f"{r['id']}: {r['status']} → {r['target']}" for r in frame.responders]))
    fig.update_xaxes(range=[0, 20], dtick=5, title="km east", constrain="domain")
    fig.update_yaxes(range=[0, 20], dtick=5, title="km north", scaleanchor="x", constrain="domain")
    fig.update_layout(height=620, margin=dict(l=10, r=10, t=10, b=10), uirevision="map",
                      legend=dict(orientation="h", y=-0.12))
    return fig


def sidebar_selection():
    runs = runs_index()
    st.sidebar.header("Run")
    scenario = st.sidebar.selectbox("Scenario", sorted({r.scenario for r in runs}))
    in_scenario = [r for r in runs if r.scenario == scenario]
    numbers = sorted({r.run_number for r in in_scenario})
    number = st.sidebar.selectbox("Run (1-10 = seed 42-51)", numbers)
    modes = [m for m in MODE_ORDER if any(r.mode == m and r.run_number == number for r in in_scenario)]
    mode = st.sidebar.selectbox("System", modes, index=modes.index("negotiation") if "negotiation" in modes else 0)
    return next(r for r in in_scenario if r.run_number == number and r.mode == mode)


def init_state(run):
    key = (run.scenario, run.seed, run.mode)
    if st.session_state.get("run_key") != key:
        st.session_state.update(run_key=key, minute=0, playing=False, advance=False)
    if st.session_state.pop("advance", False):
        st.session_state.minute += 1


def main():
    st.set_page_config(page_title="Emergency response replay", layout="wide")
    run = sidebar_selection()
    replay = load_replay(str(run.path), run.scenario, run.seed, run.mode)
    init_state(run)
    last = replay.last_minute
    if st.session_state.minute >= last:
        st.session_state.minute, st.session_state.playing = last, False

    c1, c2, c3 = st.sidebar.columns(3)
    if c1.button("⏯ Play" if not st.session_state.playing else "⏸ Pause", width="stretch"):
        st.session_state.playing = not st.session_state.playing
        if st.session_state.playing and st.session_state.minute >= last:
            st.session_state.minute = 0
        st.rerun()
    if c2.button("⏮ Restart", width="stretch"):
        st.session_state.update(minute=0, playing=False)
        st.rerun()
    st.sidebar.slider("Minute", 0, last, key="minute")
    shown = st.sidebar.multiselect("Feed", list(CATEGORIES), default=["agent", "conflict", "action"],
                                   format_func=lambda c: f"{CATEGORIES[c]} {c}")
    minute = st.session_state.minute
    frame = replay.frame(minute)

    head, kpi = st.columns([1, 3])
    head.markdown(f"<div style='font-size:4.5rem;font-weight:700;line-height:1'>{minute}<span style='font-size:1.5rem'> min</span></div>"
                  f"<div>{run.scenario} · run {run.run_number} (seed {run.seed}) · {run.mode}</div>", unsafe_allow_html=True)
    k = frame.kpis
    cols = kpi.columns(4)
    cols[0].metric("Active incidents", k["active_incidents"])
    cols[1].metric("Victims waiting", k["waiting_victims"])
    cols[2].metric("Critical waiting", k["critical_waiting"])
    cols[3].metric("Ambulances busy", f"{k['ambulances_busy']}/{k['ambulances_busy'] + k['ambulances_available']}")

    left, right = st.columns([3, 2])
    left.plotly_chart(build_map(frame), width="stretch")
    with right:
        st.subheader("Hospital ER occupancy")
        for h in frame.hospitals:
            st.progress(min(h["er_fraction"], 1.0), text=f"{h['id']}: {h['er_occupied']}/{h['er_capacity']} ER · "
                                                       f"treatment {h['treatment_in_use']}/{h['treatment_slots']}")
        st.subheader("Event feed (newest first)")
        items = [i for i in feed_items(replay.events_until(minute)) if i.category in shown]
        with st.container(height=380):
            for item in items:
                st.markdown(f"**{item.t}'** {item.icon} {item.text}")
            if not items:
                st.caption("Nothing yet.")

    if st.session_state.playing:
        time.sleep(STEP_SECONDS)
        st.session_state.advance = True
        st.rerun()


main()
