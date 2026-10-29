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
