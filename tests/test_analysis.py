"""Final analysis (scripts/analysis.py): reads saved results and logs only, never writes outside results/analysis."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from erc.config import PROJECT_ROOT, RESULTS_DIR
from erc.eval.experiment import load_runs

spec = importlib.util.spec_from_file_location("analysis", PROJECT_ROOT / "scripts" / "analysis.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def tables():
    before = {v: digest(RESULTS_DIR / v / "runs.jsonl") for v in analysis.VERSIONS}
    out = analysis.build_all()
    assert before == {v: digest(RESULTS_DIR / v / "runs.jsonl") for v in analysis.VERSIONS}      # inputs untouched
    return out


def test_outputs_go_to_results_analysis_only():
    assert analysis.OUT == RESULTS_DIR / "analysis"


def test_rebuilt_per_victim_outcomes_match_saved_metrics(tables):
    check = tables["00_reconstruction_check"]
    assert len(check) == sum(len(load_runs(v)) for v in analysis.VERSIONS)
    assert check["csr_matches"].all() and check["response_matches"].all()


def test_every_table_is_labelled_by_version(tables):
    for name, df in tables.items():
        if name not in ("05_v1_vs_v2_critical_service",) and len(df):
            assert "version" in df.columns, name
            assert set(df["version"]) <= set(analysis.VERSIONS)


def test_headline_tables_agree_with_saved_paired_csvs(tables):
    saved = pd.read_csv(RESULTS_DIR / "v1" / "paired_vs_greedy.csv")
    mine = tables["01_rq1_paired_vs_greedy"]
    for _, row in saved.iterrows():
        m = mine[(mine.version == "v1") & (mine.scenario == row["scenario"]) & (mine["mode"] == row["mode"])].iloc[0]
        assert m["mean_diff"] == pytest.approx(row["mean_diff"])
        assert f"{m['wins']}/{m['losses']}/{m['ties']}" == row["wins/losses/ties"]


def test_agents_beat_naive_in_every_scenario_and_version(tables):
    t = tables["01_rq1_vs_naive"]
    a = t[t["mode"].isin(["agents", "negotiation"])]
    assert len(a) == 12 and a["significant"].all() and a["ci_low"].gt(0).all()             # README: +10.9 to +23.3 points, none touches zero
    assert round(a["mean_diff"].min() * 100, 1) == 10.9 and round(a["mean_diff"].max() * 100, 1) == 23.3
    g = t[t["mode"] == "greedy"]
    assert sorted(round(x * 100, 1) for x in g[g.version == "v1"]["mean_diff"]) == [8.7, 11.2, 22.7]


def test_divergence_summary_counts_add_up(tables):
    s = tables["02_divergence_summary"]
    for r in s.itertuples():
        assert r.diverged + r.never_diverged == r.paired_runs
        assert r.helped + r.hurt + r.tied == r.diverged
    d = tables["02_divergence"]
    assert (d[~d.diverged]["csr_diff"] == 0).all()           # identical histories give identical outcomes


def test_known_counter_offer_is_found():
    events = analysis.load_events("v1", "negotiation", "normal", 42)
    rows = analysis.conflict_rows("v1", "normal", 42, "negotiation", events, None)
    first = next(r for r in rows if r["conflict_id"] == "t006-C01")
    assert first["resolution"] == "counter-offer accepted" and first["counter_victims"] == "V-01-1" and first["counter_critical_in_time"] == 1


def test_lost_cause_buckets():
    base = {"assign_t": 3, "assign_unit": "AMB-01", "contact": 10, "unit": "AMB-01"}
    assert analysis.lost_cause({**base, "assign_t": None, "contact": None}, base) == "never reached, no ambulance ever assigned"
    assert analysis.lost_cause({**base, "contact": None}, base) == "never reached, ambulance assigned too late"
    assert analysis.lost_cause({**base, "assign_t": 9}, base) == "ambulance dispatched later than greedy"
    assert analysis.lost_cause({**base, "assign_unit": "AMB-02"}, base) == "different (slower) ambulance than greedy"


def test_contention_ambulance_conflicts_fall_and_er_never_fills(tables):
    t = tables["04_contention"]
    for v in analysis.VERSIONS:
        g = t[t.version == v].set_index("scenario")
        assert g.loc["normal", "ambulance_conflicts_per_run"] > g.loc["surge", "ambulance_conflicts_per_run"] > g.loc["bottleneck", "ambulance_conflicts_per_run"]
        assert g.loc["normal", "critical_per_als_ambulance"] < g.loc["surge", "critical_per_als_ambulance"] < g.loc["bottleneck", "critical_per_als_ambulance"]
        assert (g["runs_with_er_full_greedy"] == 0).all() and (g["runs_with_er_full_negotiation"] == 0).all()


def test_all_invalid_proposals_were_blocked_before_execution(tables):
    rel = tables["06_reliability_summary"]
    assert (rel["actions_rejected_at_execution"] == 0).all() and rel["proposals_invalid"].sum() > 0
    inv = tables["06_invalid_proposals"]
    assert (inv[inv.kind.str.startswith("proposal")]["count"].sum() == rel["proposals_invalid"].sum())
