"""Negotiations page: every conflict and hospital-admission negotiation of one saved run.

Pick a run, pick a negotiation from the list, read its steps in order and open the raw structured message
behind any step. Read-only: built from the event log (no simulation, no API calls).
"""
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pandas as pd
import streamlit as st

import common

from erc.dashboard.negotiations import is_notable, negotiation_records
from erc.dashboard.replay import MODE_ORDER, available_runs

SCENARIO_ORDER = ["normal", "surge", "bottleneck"]
DEFAULTS = {"version": "v2", "scenario": "normal", "run": 1, "mode": "negotiation"}
FILTERS = {"All": lambda r: True, "Conflicts": lambda r: r["kind"] == "conflict",
           "Hospital admissions": lambda r: r["kind"] == "admission", "Notable only": is_notable}
STEP_COLORS = {"conflict": "#e4574f", "proposal": "#6fa8dc", "counter": "#e0a64a", "accept": "#54b87a", "reject": "#cf6f93",
               "escalate": "#d98558", "resolved": "#a78bd6", "fallback": "#d98558", "commit": "#5fb3a5", "info": "#8a9bb0"}
LIST_HEIGHT = 640


@st.cache_data
def runs_index():
    return available_runs()


@st.cache_data(show_spinner=False)
def records_for(path: str) -> list[dict]:
    events = [json.loads(line) for line in Path(path).read_text().splitlines() if line]
    return negotiation_records(events)


def pick(col, label, options, preferred, key, format_func=str):
    index = options.index(preferred) if preferred in options else 0
    return col.selectbox(label, options, index=index, key=key, format_func=format_func)


def step_card(step: dict) -> str:
    color = STEP_COLORS.get(step["key"], "#8a9bb0")
    who = f"{html.escape(step['from'])} &rarr; {html.escape(step['to'])}" if step["to"] else html.escape(step["from"])
    why = f"<div class='ng-why'>{html.escape(step['why'])}</div>" if step["why"] else ""
    return (f"<div class='ng-step' style='border-left-color:{color}'><div class='ng-top'>"
            f"<span class='ng-badge' style='background:{color}'>{html.escape(step['label'].upper())}</span>"
            f"<span class='ng-who'>{who}</span><span class='ng-id'>minute {step['t']} &middot; {html.escape(step['id'])}</span></div>"
            f"<div class='ng-text'>{html.escape(step['text'])}</div>{why}</div>")


common.setup()
st.markdown("""<style>
.ng-step{background:#121b27;border:1px solid #243246;border-left:4px solid #8a9bb0;border-radius:8px;padding:7px 12px;margin:6px 0 2px 0}
.ng-top{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.ng-badge{font-size:.7rem;font-weight:700;letter-spacing:.06em;color:#0b1118;padding:1px 8px;border-radius:4px}
.ng-who{font-size:.9rem;color:#a9b8cb}.ng-id{margin-left:auto;font-size:.8rem;color:#8a9bb0;font-family:ui-monospace,Menlo,monospace}
.ng-text{font-size:1.02rem;color:#dbe3ee;margin-top:3px}.ng-why{font-size:.88rem;color:#8a9bb0;margin-top:2px}
.ng-head{font-size:1.2rem;font-weight:700;color:#dbe3ee}.ng-meta{font-size:.95rem;color:#a9b8cb;margin-bottom:4px}
</style>""", unsafe_allow_html=True)
slot, (c_version, c_scenario, c_run, c_mode) = common.header((0.8, 1.0, 1.3, 1.4))
runs = runs_index()
version = pick(c_version, "Version", sorted({r.version for r in runs}), DEFAULTS["version"], "ng_version")
in_version = [r for r in runs if r.version == version]
scenario = pick(c_scenario, "Scenario", [s for s in SCENARIO_ORDER if any(r.scenario == s for r in in_version)], DEFAULTS["scenario"], "ng_scenario")
in_scenario = [r for r in in_version if r.scenario == scenario]
number = pick(c_run, "Run", sorted({r.run_number for r in in_scenario}), DEFAULTS["run"], "ng_run", lambda n: f"Run {n} (seed {n + 41})")
modes = [m for m in MODE_ORDER if any(r.mode == m and r.run_number == number for r in in_scenario)]
mode = pick(c_mode, "System", modes, DEFAULTS["mode"], "ng_mode")
run = next(r for r in in_scenario if r.run_number == number and r.mode == mode)
common.subtitle(slot, f"Negotiations &middot; {scenario.title()} scenario &middot; run {number} (seed {run.seed}) &middot; {mode} system &middot; {version}")

records = records_for(str(run.path))
choice = st.radio("Show", list(FILTERS), horizontal=True, key="ng_filter", label_visibility="collapsed")
shown = [r for r in records if FILTERS[choice](r)]
if not records:
    st.markdown(f"<div class='cc-note'>The {mode} system has no conflicts or negotiations in this run.</div>", unsafe_allow_html=True)
elif not shown:
    st.markdown("<div class='cc-note'>No negotiations match this filter.</div>", unsafe_allow_html=True)
else:
    left, right = st.columns([1.5, 1.7], gap="medium")
    table = pd.DataFrame([{"Min": r["t"], "Type": r["type"], "Incidents": ", ".join(r["incidents"]), "Units": ", ".join(r["units"]),
                           "Steps": len(r["steps"]), "Outcome": r["outcome"]} for r in shown])
    with left:
        event = st.dataframe(table, hide_index=True, use_container_width=True, height=LIST_HEIGHT, on_select="rerun",
                             column_config={"Type": st.column_config.TextColumn(width="medium"), "Min": st.column_config.NumberColumn(width="small"),
                                            "Steps": st.column_config.NumberColumn(width="small"), "Outcome": st.column_config.TextColumn(width="large")},
                             selection_mode="single-row", key=f"ng_table_{run.path.name}_{choice}")
        st.caption(f"{len(shown)} of {len(records)} negotiations. Click a row to see its steps.")
    rows = event.selection.rows
    record = shown[rows[0]] if rows else shown[0]
    with right:
        box = st.container(height=LIST_HEIGHT + 30)
        with box:
            st.markdown(f"<div class='ng-head'>{record['id']} &middot; {record['type']}</div>"
                        f"<div class='ng-meta'>minute {record['t']} &middot; incidents {', '.join(record['incidents'])} &middot; "
                        f"units {', '.join(record['units'])} &middot; {record['rounds']} round{'s' if record['rounds'] != 1 else ''} "
                        f"&middot; <b>{record['outcome']}</b></div>", unsafe_allow_html=True)
            for step in record["steps"]:
                st.markdown(step_card(step), unsafe_allow_html=True)
                with st.expander(f"Raw JSON message · {step['id']}"):
                    st.json(step["raw"])
