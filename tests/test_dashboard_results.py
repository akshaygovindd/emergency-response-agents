"""Tests: Results page tables match the saved summary and paired CSVs, and takeaways cite the numbers."""
import pandas as pd
import pytest

from erc.config import RESULTS_DIR
from erc.dashboard import results_view as rv


@pytest.fixture(scope="module", params=["v1", "v2"])
def version(request):
    if not (RESULTS_DIR / request.param / "runs.jsonl").exists():
        pytest.skip("saved results not available")
    return request.param


def test_csr_table_matches_summary_csv(version):
    runs = rv.runs_for(version)
    mine = rv.csr_table(runs).set_index(["scenario", "mode"])["mean"]
    saved = pd.read_csv(RESULTS_DIR / version / "summary.csv").set_index(["scenario", "mode"])["critical_service_rate"]
    for key, value in saved.items():
        assert mine[key] == pytest.approx(value)


def test_paired_table_matches_paired_csv(version):
    runs = rv.runs_for(version)
    saved = pd.read_csv(RESULTS_DIR / version / "paired_vs_greedy.csv")
    for row in saved.itertuples():
        mine = rv.paired_table(runs, row.mode, "greedy").set_index("scenario").loc[row.scenario]
        assert mine["mean_diff"] == pytest.approx(row.mean_diff)
        assert bool(mine["significant"]) == bool(row.significant)
        assert f"{mine['wins']}/{mine['losses']}/{mine['ties']}" == row._asdict()["_8"]


def test_every_table_is_one_version_and_labelled_in_takeaways(version):
    runs = rv.runs_for(version)
    assert {r["version"] for r in runs} == {version}
    by_mode = {m: rv.paired_table(runs, m, "greedy") for m in ("naive", "agents", "negotiation")}
    for text in (rv.takeaway_csr(rv.csr_table(runs), version), rv.takeaway_rq1(by_mode, version),
                 rv.takeaway_paired(rv.paired_table(runs, "negotiation", "agents"), version, "Negotiation vs agents"),
                 rv.takeaway_triage(rv.triage_table(runs), version),
                 rv.takeaway_cost(rv.cost_table(runs), version, by_mode["negotiation"]),
                 rv.takeaway_oracle(rv.paired_table(runs, "oracle", "negotiation"), version)):
        assert text.startswith(f"({version})")


def test_oracle_ablation_exists_in_v1_only():
    assert not rv.paired_table(rv.runs_for("v1"), "oracle", "negotiation").empty
    assert rv.paired_table(rv.runs_for("v2"), "oracle", "negotiation").empty
    assert "v1 only" in rv.takeaway_oracle(rv.paired_table(rv.runs_for("v2"), "oracle", "negotiation"), "v2")


def test_triage_rates_are_weighted_shares_between_0_and_1(version):
    t = rv.triage_table(rv.runs_for(version))
    assert set(t["color"]) == {"Immediate", "Delayed", "Minor"} and t["rate"].between(0, 1).all()


def test_cost_table_has_only_agent_systems_with_positive_cost(version):
    t = rv.cost_table(rv.runs_for(version))
    assert set(t["mode"]) <= set(rv.AGENT_SYSTEMS) and (t["cost_usd"] > 0).all()


def test_takeaway_paired_counts_significant_scenarios():
    t = pd.DataFrame([{"scenario": "normal", "mean_diff": 0.1, "significant": True, "n": 5},
                      {"scenario": "surge", "mean_diff": -0.02, "significant": False, "n": 5}])
    text = rv.takeaway_paired(t, "v9", "X")
    assert "normal +10.0" in text and "surge -2.0" in text and "1 of 2 scenarios" in text


def test_results_payload_is_json_serialisable_and_labelled(version):
    import json
    payload = rv.results_payload(version)
    json.dumps(payload)                                                  # must be plain data for the page
    assert payload["version"] == version and version in payload["label"] and payload["source"] == f"results/{version}/runs.jsonl"
    assert set(payload["takeaways"]) == {"csr", "rq1", "rq2", "oracle", "triage", "cost"}
    assert all(t.startswith(f"({version})") for t in payload["takeaways"].values())
    assert set(payload["vs_greedy"]) == {"naive", "agents", "negotiation"} and len(payload["csr"]) >= 12


def test_results_payload_values_match_the_tables(version):
    payload = rv.results_payload(version)
    runs = rv.runs_for(version)
    row = next(r for r in payload["csr"] if r["scenario"] == "normal" and r["mode"] == "greedy")
    mine = rv.csr_table(runs).query("scenario == 'normal' and mode == 'greedy'").iloc[0]
    assert row["mean"] == pytest.approx(mine["mean"]) and row["ci_low"] <= row["mean"] <= row["ci_high"]
    assert bool(payload["oracle"]) == (version == "v1")
