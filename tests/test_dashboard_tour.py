"""Tests: tour moments are computed from the log (first incident, assessment, conflict, counter, admission, final)."""
import json

import pytest

from erc.dashboard.export import export_replay
from erc.dashboard.replay import LOGS_DIR
from erc.dashboard.tour import tour_moments

KPIS = {"crit_ok": 3, "crit_n": 4, "reached": 5, "arrived": 6, "conflicts": 0, "negotiated": 0}


def test_minimal_run_has_first_incident_and_final_only():
    events = [{"t": 4, "kind": "incident_arrived", "incident_id": "INC-01", "victims": 2, "max_severity": 3}]
    moments = tour_moments(events, [], 120, KPIS, 4)
    assert [m["title"] for m in moments] == ["First incident", "Final outcome"]
    assert moments[0]["t"] == 4 and "INC-01" in moments[0]["caption"] and "2 victims" in moments[0]["caption"]
    assert moments[-1]["t"] == 120 and "3 of 4 critical" in moments[-1]["caption"]


def test_admission_decision_prefers_a_changed_destination():
    resolved = lambda t, method, hosp: {"t": t, "kind": "admission_resolved", "negotiation_id": f"ADM-{t}", "incident_id": "INC-02",
                                        "victim_ids": ["V-1"], "requested": "H-T", "hospital_id": hosp, "method": method, "rounds": 2}
    events = [resolved(5, "accepted", "H-T"), resolved(9, "revised", "H-G")]
    moment = next(m for m in tour_moments(events, [], 60, KPIS, 4) if m["title"] == "Hospital admission decision")
    assert moment["t"] == 9 and "H-T could not take V-1" in moment["caption"] and "H-G" in moment["caption"]


def test_moments_are_in_time_order_with_final_last():
    for version, mode in (("v1", "negotiation"), ("v2", "negotiation"), ("v1", "greedy")):
        if not (LOGS_DIR / version / mode / "normal_seed42_" f"{mode}.jsonl").exists():
            pytest.skip("saved run not available")
        tour = export_replay(version, "normal", 42, mode)["tour"]
        times = [m["t"] for m in tour]
        assert times == sorted(times) and tour[-1]["title"] == "Final outcome" and tour[0]["title"] == "First incident"
        assert all(m["caption"] for m in tour)


def test_real_negotiation_run_tour_has_conflict_counter_and_v2_admission():
    log = LOGS_DIR / "v2" / "negotiation" / "normal_seed42_negotiation.jsonl"
    if not log.exists():
        pytest.skip("saved v2 run not available")
    titles = [m["title"] for m in export_replay("v2", "normal", 42, "negotiation")["tour"]]
    assert titles[:3] == ["First incident", "First assessment", "First conflict"]
    assert "Counter-offer accepted" in titles and "Hospital admission decision" in titles
    v1 = [m["title"] for m in export_replay("v1", "normal", 42, "negotiation")["tour"]]
    assert "Hospital admission decision" not in v1       # v1 has no admission negotiation


def test_every_saved_run_has_a_tour():
    from erc.dashboard.replay import available_runs
    for run in available_runs():
        tour = export_replay(run.version, run.scenario, run.seed, run.mode)["tour"]
        assert len(tour) >= 2
