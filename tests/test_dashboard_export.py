"""Tests: the replay bundle is built from the log alone and carries every decision the player needs."""
import json

import pytest

from erc.dashboard.export import (
    EXPECTANT, HIDDEN, IMMEDIATE, MINOR, REACHED, build_bundle, export_replay, first_contacts, unit_trips,
)
from erc.dashboard.replay import LOGS_DIR, ROOT

LAST = 8


def scenario():
    victim = lambda vid, sev, dl: {"victim_id": vid, "severity": sev, "deadline_min": dl}
    return {
        "hospitals": [{"hospital_id": "H1", "name": "Trauma Center", "location": {"x": 10, "y": 10},
                       "er_capacity": 4, "treatment_slots": {"trauma": 2, "general": 1}}],
        "ambulances": [{"ambulance_id": "AMB-01", "ambulance_type": "advanced_life_support"}],
        "responders": [{"team_id": "MED-1", "responder_type": "medical"}],
        "incidents": [{"incident_id": "INC-01", "location": {"x": 4, "y": 0}, "arrival_time_min": 2,
                       "victims": [victim("V-01", 4, 2), victim("V-02", 2, 30)]}],
    }


def snapshot(t):
    statuses = {"V-01": "waiting", "V-02": "waiting"}
    amb_status = "en_route" if 2 <= t < 6 else "on_scene" if t >= 6 else "available"
    return {
        "t": t, "kind": "snapshot", "time_min": t, "active_incidents": 1, "waiting_victims": 2,
        "critical_waiting": 1, "ambulances_busy": 1, "ambulances_available": 0,
        "ambulances": [{"id": "AMB-01", "x": 4.0 if t >= 6 else 0.0, "y": 0.0, "status": amb_status,
                        "target": "INC-01" if t >= 2 else None, "onboard": []}],
        "responders": [{"id": "MED-1", "x": 1.0, "y": 1.0, "status": "available", "target": None}],
        "incidents": [{"id": "INC-01", "x": 4.0, "y": 0.0,
                       "victims": [{"id": v, "severity": 4 if v == "V-01" else 2, "status": s}
                                   for v, s in statuses.items()]}] if t >= 2 else [],
        "hospitals": [{"id": "H1", "er_occupied": 1 if t >= 7 else 0, "er_capacity": 4,
                       "treatment_in_use": 0, "treatment_slots": 3}],
    }


def events():
    log = [snapshot(t) for t in range(LAST + 1)]
    log += [
        {"t": 2, "kind": "action_accepted", "incident_id": "INC-01", "source": "dispatch", "message_id": "m",
         "action": {"action_type": "assign_ambulance", "ambulance_id": "AMB-01", "victim_ids": ["V-01"]}},
        {"t": 3, "kind": "action_accepted", "incident_id": "INC-01", "source": "hospital", "message_id": "m",
         "action": {"action_type": "admit_patient", "hospital_id": "H1", "victim_ids": ["V-01"]}},
        {"t": 6, "kind": "ambulance_on_scene", "ambulance_id": "AMB-01", "incident_id": "INC-01"},
        {"t": 7, "kind": "handover_complete", "ambulance_id": "AMB-01", "hospital_id": "H1", "victim_ids": ["V-01"]},
    ]
    return log


@pytest.fixture
def bundle():
    return build_bundle(events(), scenario(), {"version": "vX", "scenario": "normal", "seed": 42, "mode": "m"})


def codes(bundle, victim_id):
    i = next(i for i, v in enumerate(bundle["victims"]) if v["id"] == victim_id)
    return [f["v"][i] for f in bundle["frames"]]


def test_one_frame_per_minute_and_json_serialisable(bundle):
    assert [f["t"] for f in bundle["frames"]] == list(range(LAST + 1))
    assert bundle["meta"]["last_minute"] == LAST
    json.dumps(bundle)


def in_time_order(log):
    return sorted(log, key=lambda e: e["t"])        # real logs are written in time order


def test_first_contact_from_ambulance_and_medical_team():
    assert first_contacts(events(), scenario()) == {"V-01": 6}      # the ambulance was assigned V-01 only
    arrival = {"t": 4, "kind": "responder_arrived", "team_id": "MED-1", "incident_id": "INC-01"}
    contact = first_contacts(in_time_order(events() + [arrival]), scenario())
    assert contact == {"V-01": 4, "V-02": 4}       # a medical team reaches everyone still waiting
    fire = {**arrival, "team_id": "FIRE-1"}
    assert first_contacts(in_time_order(events() + [fire]), scenario()) == {"V-01": 6}   # other teams do not count


def test_triage_colours_expectant_and_reached(bundle):
    # V-01: severity 4, deadline 2, arrives at minute 2, reached at minute 6
    assert codes(bundle, "V-01") == [HIDDEN, HIDDEN, IMMEDIATE, IMMEDIATE, IMMEDIATE,
                                     EXPECTANT, REACHED, REACHED, REACHED]
    # V-02: severity 2 (minor), never assigned an ambulance
    assert codes(bundle, "V-02") == [HIDDEN, HIDDEN] + [MINOR] * 7


def test_noncritical_victim_never_turns_expectant(bundle):
    assert EXPECTANT not in codes(bundle, "V-02")


def test_trip_covers_the_move_in_a_straight_line(bundle):
    [trip] = [t for t in bundle["trips"] if t["unit"] == "AMB-01"]
    assert (trip["t0"], trip["t1"]) == (2, 6)
    assert (trip["x0"], trip["y0"], trip["x1"], trip["y1"]) == (0.0, 0.0, 4.0, 0.0)
    assert trip["target"] == "INC-01" and trip["kind"] == "ambulance"
    assert [f["a"][0][0] for f in bundle["frames"]][2:7] == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_a_turn_starts_a_new_trip():
    path = [(0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (2, 2)]
    trips = unit_trips("U", "ambulance", path, ["T"] * len(path))
    assert [(t["t0"], t["t1"]) for t in trips] == [(0, 2), (2, 4)]


def test_promised_beds_until_handover(bundle):
    promised = [f["h"][0][2] for f in bundle["frames"]]
    assert promised == [0, 0, 0, 1, 1, 1, 1, 0, 0]
    assert bundle["frames"][7]["h"][0][0] == 1       # ER occupancy comes from the snapshot


def test_static_lists_and_labels(bundle):
    assert bundle["hospitals"][0]["label"] == "Trauma" and bundle["hospitals"][0]["er_capacity"] == 4
    assert bundle["ambulances"] == [{"id": "AMB-01", "als": True}]
    assert bundle["responders"] == [{"id": "MED-1", "kind": "medical"}]


# ───────── Real saved run (read-only): the bundle agrees with the results table ─────────
def test_real_run_matches_saved_critical_service_rate():
    log = LOGS_DIR / "v1" / "negotiation" / "normal_seed42_negotiation.jsonl"
    results = ROOT / "results" / "v1" / "runs.jsonl"
    if not log.exists() or not results.exists():
        pytest.skip("saved v1 run not available")
    b = export_replay("v1", "normal", 42, "negotiation")
    critical = [v for v in b["victims"] if v["severity"] >= 4]
    served = sum(v["contact_min"] is not None and v["contact_min"] - v["arrival_min"] <= v["deadline_min"]
                 for v in critical)
    row = next(r for r in map(json.loads, results.read_text().splitlines())
               if (r["scenario"], r["seed"], r["mode"]) == ("normal", 42, "negotiation"))
    assert served / len(critical) == pytest.approx(row["critical_service_rate"])
    assert len(b["frames"]) == 121 and b["trips"]


# ───────── Player page ─────────
def test_player_page_is_self_contained(bundle):
    from erc.dashboard.player import render_player
    html = render_player(bundle)
    assert "__BUNDLE__" not in html and "/*__JS__*/" not in html and "/*__CSS__*/" not in html
    assert '"frames"' in html and "requestAnimationFrame" in html
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")     # no CDN, works offline
    assert "https://" not in html and "<script src" not in html and "<link " not in html


def test_bundle_text_cannot_break_out_of_the_script_tag(bundle):
    from erc.dashboard.player import render_player
    bundle["meta"]["note"] = "</script><script>alert(1)</script>"
    html = render_player(bundle)
    assert html.count("</script>") == 2          # the bundle block and the player block only


def test_every_saved_run_exports():
    """Every run offered in the dashboard builds a complete, serialisable bundle."""
    from erc.dashboard.replay import available_runs
    runs = available_runs()
    if not runs:
        pytest.skip("no saved logs")
    for run in runs:
        b = export_replay(run.version, run.scenario, run.seed, run.mode)
        assert len(b["frames"]) == b["meta"]["last_minute"] + 1 == 121, run.path.name
        assert all(len(f["v"]) == len(b["victims"]) for f in b["frames"]), run.path.name
        assert all(0 <= t["t0"] < t["t1"] <= 120 for t in b["trips"]), run.path.name
        json.dumps(b)
