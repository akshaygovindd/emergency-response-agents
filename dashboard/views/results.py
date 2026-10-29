"""Results page: the evidence from results/v1 and results/v2, one chart per question, always labelled by version.

Read-only: charts are computed from results/<version>/runs.jsonl (no simulation, no API calls). Every
takeaway sentence is generated from the numbers in the chart above it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import common

from erc.dashboard import results_view as rv

COLORS = {"naive": "#7f93aa", "greedy": "#e0a64a", "agents": "#6fa8dc", "negotiation": "#54b87a", "oracle": "#a78bd6"}
TRIAGE_COLORS = {"Immediate": "#e4574f", "Delayed": "#ecc24a", "Minor": "#54b87a"}
PLOT = dict(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0e1621", height=600,
            margin=dict(l=60, r=20, t=110, b=40), font=dict(size=15), legend=dict(orientation="h", y=1.09, x=0))


@st.cache_data(show_spinner=False)
def tables(version: str) -> dict:
    runs = rv.runs_for(version)
    return {"csr": rv.csr_table(runs), "vs_greedy": {m: rv.paired_table(runs, m, "greedy") for m in ("naive", "agents", "negotiation")},
            "rq2": rv.paired_table(runs, "negotiation", "agents"), "oracle": rv.paired_table(runs, "oracle", "negotiation"),
            "triage": rv.triage_table(runs), "cost": rv.cost_table(runs)}


def bars(rows, title, y_title, percent=True):
    """rows: list of (name, color, x labels, y, ci_low, ci_high, hover)"""
    fig = go.Figure()
    for name, color, xs, ys, lo, hi, hover in rows:
        fig.add_bar(name=name, x=xs, y=ys, marker_color=color, hovertext=hover, hoverinfo="text",
                    error_y=dict(type="data", symmetric=False, array=[h - y for h, y in zip(hi, ys)],
                                 arrayminus=[y - l for y, l in zip(ys, lo)], color="#dbe3ee", thickness=1.4, width=4))
    fig.update_layout(title=title, barmode="group", yaxis=dict(title=y_title, tickformat=".0%" if percent else None), **PLOT)
    if y_title.startswith("critical victims"):
        fig.update_yaxes(tickvals=[0, .2, .4, .6, .8, 1.0])        # intervals may reach past 100% with few seeds; no tick there
    return fig


def chart_csr(t, version):
    rows = []
    for mode in rv.SYSTEMS:
        g = t[t["mode"] == mode]
        if g.empty:
            continue
        label = lambda r: f"{r.mode} on {r.scenario}: {r.mean:.1%} [{r.ci_low:.1%}, {r.ci_high:.1%}] (n={r.n} seeds)"
        rows.append((mode + (f" (n={int(g['n'].iloc[0])} seeds)" if mode == "oracle" else ""), COLORS[mode], list(g["scenario"]),
                     list(g["mean"]), list(g["ci_low"]), list(g["ci_high"]), [label(r) for r in g.itertuples()]))
    return bars(rows, f"Critical victim service rate by scenario and system, 95% CI ({version})", "critical victims served in time")


def chart_paired(tables_by_mode, title, version):
    rows = []
    for mode, t in tables_by_mode.items():
        if t.empty:
            continue
        label = lambda r: (f"{r.mode} minus {r.vs} on {r.scenario}: {r.mean_diff * 100:+.1f} pts [{r.ci_low * 100:+.1f}, {r.ci_high * 100:+.1f}], "
                           f"wins/losses/ties {r.wins}/{r.losses}/{r.ties}")
        rows.append((f"{mode} minus {t['vs'].iloc[0]}", COLORS[mode], list(t["scenario"]), list(t["mean_diff"]),
                     list(t["ci_low"]), list(t["ci_high"]), [label(r) for r in t.itertuples()]))
    fig = bars(rows, f"{title} ({version})", "difference in critical service rate (paired by seed)")
    fig.add_hline(y=0, line_color="#8a9bb0", line_width=1.5)
    return fig


def chart_triage(t, version):
    colors = list(rv.TRIAGE)
    fig = make_subplots(rows=1, cols=3, shared_yaxes=True, subplot_titles=colors)
    for i, color in enumerate(colors, start=1):
        for mode in rv.SYSTEMS:
            g = t[(t["color"] == color) & (t["mode"] == mode)]
            if g.empty:
                continue
            fig.add_bar(name=mode, x=list(g["scenario"]), y=list(g["rate"]), marker_color=COLORS[mode], showlegend=i == 1,
                        legendgroup=mode, hovertext=[f"{mode} on {r.scenario}, {color}: {r.rate:.1%} (n={r.n} runs)" for r in g.itertuples()],
                        hoverinfo="text", row=1, col=i)
    for ann, color in zip(fig.layout.annotations, colors):
        ann.font = dict(size=17, color=TRIAGE_COLORS[color])
    fig.update_layout(title=f"Victims served in time by triage colour ({version})", barmode="group",
                      yaxis=dict(tickformat=".0%", title="served in time"), **PLOT)
    return fig


def chart_cost(t, version):
    fig = go.Figure()
    for mode in rv.AGENT_SYSTEMS:
        g = t[t["mode"] == mode]
        if g.empty:
            continue
        fig.add_bar(name=mode, x=list(g["scenario"]), y=list(g["cost_usd"]), marker_color=COLORS[mode],
                    text=[f"${c:.3f}" for c in g["cost_usd"]], textposition="outside",
                    hovertext=[f"{mode} on {r.scenario}: ${r.cost_usd:.3f} per run, {r.tokens:,.0f} tokens, {r.calls:.0f} LLM calls, {r.latency_s:.0f} s model time"
                               for r in g.itertuples()], hoverinfo="text")
    fig.update_layout(title=f"Cost per run at list price ({version})", barmode="group",
                      yaxis=dict(title="USD per run (naive and greedy: $0)", tickformat="$.2f"), **PLOT)
    return fig


def show(fig, takeaway):
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(f"<div class='cc-note'>{takeaway}</div>", unsafe_allow_html=True)


common.setup()
st.markdown("<style>.stTabs [data-baseweb='tab']{font-size:1rem;padding:0.4rem 1rem}</style>", unsafe_allow_html=True)
slot, (c_version,) = common.header("Results", (1.6,))
version = c_version.selectbox("Results version", list(rv.FRAMES), format_func=rv.FRAMES.get, key="res_version")
common.subtitle(slot, f"Results &middot; <b>{rv.FRAMES[version]}</b> &middot; from results/{version}/runs.jsonl")
d = tables(version)

tabs = st.tabs(["Service rate", "RQ1 · vs greedy", "RQ2 · negotiation vs agents", "Oracle ablation", "Triage colour", "RQ4 · cost"])
with tabs[0]:
    show(chart_csr(d["csr"], version), rv.takeaway_csr(d["csr"], version))
with tabs[1]:
    show(chart_paired(d["vs_greedy"], "Paired difference vs greedy (RQ1)", version),
         rv.takeaway_rq1(d["vs_greedy"], version))
with tabs[2]:
    show(chart_paired({"negotiation": d["rq2"]}, "Negotiation vs agents without negotiation (RQ2)", version),
         rv.takeaway_paired(d["rq2"], version, "Negotiation vs agents"))
with tabs[3]:
    if d["oracle"].empty:
        st.markdown(f"<div class='cc-note'>{rv.takeaway_oracle(d['oracle'], version)}</div>", unsafe_allow_html=True)
    else:
        show(chart_paired({"oracle": d["oracle"]}, "Information ablation: oracle minus negotiation", version),
             rv.takeaway_oracle(d["oracle"], version))
with tabs[4]:
    show(chart_triage(d["triage"], version), rv.takeaway_triage(d["triage"], version))
with tabs[5]:
    show(chart_cost(d["cost"], version), rv.takeaway_cost(d["cost"], version, d["vs_greedy"]["negotiation"]))
