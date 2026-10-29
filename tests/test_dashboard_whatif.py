"""Tests: what-if scenarios are built in memory, reproduce saved scenarios, and never touch saved data."""
import json

import pytest

from erc.config import SCENARIO_DIR, SCENARIOS, ScenarioName
from erc.dashboard.whatif import build_scenario, run_system, run_whatif
from erc.models.state import Scenario


def test_original_numbers_reproduce_the_saved_scenario_exactly():
    path = SCENARIO_DIR / "normal_seed42.json"
    if not path.exists():
        pytest.skip("saved scenario not available")
    assert build_scenario(5, 12, 42) == Scenario.load(path)


def test_ambulance_and_incident_counts_follow_the_inputs():
    s = build_scenario(2, 20, 7)
    assert len(s.ambulances) == 2 and len(s.incidents) == 20
    assert [a.ambulance_id for a in s.ambulances] == ["AMB-01", "AMB-02"]       # keeps an ALS and a BLS unit
    assert len(build_scenario(5, 5, 7).ambulances) == 5


def test_frozen_settings_are_not_modified():
    before = {k: v.model_dump() for k, v in SCENARIOS.items()}
    build_scenario(2, 30, 3, ScenarioName.BOTTLENECK)
    assert {k: v.model_dump() for k, v in SCENARIOS.items()} == before


@pytest.mark.parametrize("amb, inc", [(1, 12), (6, 12), (5, 2), (5, 41)])
def test_out_of_range_inputs_are_refused(amb, inc):
    with pytest.raises(ValueError):
        build_scenario(amb, inc, 42)


def test_live_run_matches_saved_greedy_result_and_saves_nothing(tmp_path, monkeypatch):
    saved = [json.loads(line) for line in open(SCENARIO_DIR.parents[1] / "results" / "v1" / "runs.jsonl")]
    greedy = next(r for r in saved if r["scenario"] == "normal" and r["seed"] == 42 and r["mode"] == "greedy")
    logs_before = sorted(p.name for p in (SCENARIO_DIR.parents[1] / "logs").rglob("*.jsonl"))
    result = run_whatif(5, 12, 42)
    assert set(result) == {"naive", "greedy"}
    assert result["greedy"]["metrics"]["critical_service_rate"] == pytest.approx(greedy["critical_service_rate"])
    assert result["greedy"]["bundle"]["meta"]["version"] == "what-if"
    assert sorted(p.name for p in (SCENARIO_DIR.parents[1] / "logs").rglob("*.jsonl")) == logs_before


def test_run_system_returns_a_playable_bundle():
    bundle = run_system(build_scenario(3, 8, 11), "naive")["bundle"]
    assert len(bundle["frames"]) == bundle["meta"]["last_minute"] + 1 and len(bundle["ambulances"]) == 3
    assert len(bundle["incidents"]) == 8


# ───────── page helpers ─────────
def test_parse_params_clamps_and_falls_back():
    from erc.dashboard.whatif import parse_params
    assert parse_params("3", "20", "7", "surge") == (3, 20, 7, ScenarioName.SURGE)
    assert parse_params("99", "1", "-5", "nonsense") == (5, 3, 0, ScenarioName.NORMAL)          # clamped, unknown profile -> normal
    assert parse_params(None, "abc", "", None) == (5, 12, 42, ScenarioName.NORMAL)               # unusable values -> defaults


def test_summaries_and_difference_for_the_cards():
    from erc.dashboard.whatif import difference_points, summarize_run
    result = run_whatif(5, 12, 42)
    summaries = {m: summarize_run(result[m]["metrics"]) for m in result}
    assert summaries["greedy"]["csr"] == pytest.approx(10 / 11) and summaries["greedy"]["n_critical"] == 11
    assert difference_points(summaries) == pytest.approx(45.5, abs=0.1) and "critical of 26 patients" in summaries["greedy"]["served_note"]
    assert difference_points({"naive": {"csr": None}, "greedy": {"csr": 0.5}}) is None


def test_whatif_page_files_use_the_shared_shell_and_disable_agents():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "dashboard" / "whatif_app" / "page.js").read_text()
    assert 'UI.mountRail("What-if")' in js and "sys off" in js and "Agent runs take minutes and use API calls" in js and "UI.goto(\"whatif\"" in js
