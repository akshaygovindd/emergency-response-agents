"""Tests: replay must rebuild the world from a log and never invent events."""
import json

from erc.dashboard.feed import feed_event, feed_items, to_feed_item
from erc.dashboard.replay import Replay, RunRef, available_runs, interpolate_track

S = "available"


def test_interpolates_between_departure_and_arrival():
    states = [(0, 0, S, None), (0, 0, "en_route", "I"), (0, 0, "en_route", "I"),
              (0, 0, "en_route", "I"), (6, 3, "on_scene", "I")]
    track = interpolate_track(states)
    assert track[1] == (0, 0)
    assert track[2] == (2.0, 1.0)
    assert track[3] == (4.0, 2.0)
    assert track[4] == (6, 3)


def test_waiting_at_hospital_after_arrival_is_not_a_move():
    states = [(0, 0, "transporting", "H"), (0, 0, "transporting", "H"), (4, 4, "transporting", "H"),
              (4, 4, "transporting", "H"), (4, 4, "en_route", "I"), (4, 4, "en_route", "I"),
              (8, 4, "on_scene", "I")]
    track = interpolate_track(states)
    assert track[3] == (4, 4)              # handover wait: stays at the hospital
    assert track[1] == (2.0, 2.0)          # still interpolating toward the hospital
    assert track[5] == (6.0, 4.0)          # new leg starts when the status changes


def test_unfinished_move_stays_put():
    assert interpolate_track([(1, 1, S, None), (1, 1, "en_route", "I"), (1, 1, "en_route", "I")])[2] == (1, 1)


def snapshot(t, amb_status, x, y):
    return {"t": t, "kind": "snapshot", "time_min": t, "active_incidents": 1, "waiting_victims": 1,
            "critical_waiting": 1, "ambulances_busy": 1, "ambulances_available": 0,
            "ambulances": [{"id": "A", "x": x, "y": y, "status": amb_status, "target": "I", "onboard": []}],
            "responders": [], "hospitals": [{"id": "H", "er_occupied": 1, "er_capacity": 4,
                                              "treatment_in_use": 0, "treatment_slots": 2}],
            "incidents": [{"id": "I", "x": 5, "y": 5, "victims": [{"id": "V", "severity": 4, "status": "waiting"}]}]}


def small_replay():
    events = [snapshot(0, "available", 0, 0), snapshot(1, "en_route", 0, 0), snapshot(2, "en_route", 0, 0),
              {"t": 2, "kind": "action_accepted", "incident_id": "I", "source": "dispatch", "message_id": None,
               "action": {"action_type": "assign_ambulance", "ambulance_id": "A", "responder_id": None,
                          "hospital_id": None, "victim_ids": ["V"]}},
              snapshot(3, "on_scene", 4, 2)]
    return Replay(events, {"H": (9.0, 9.0)})


def test_frame_has_interpolated_units_hospitals_and_incidents():
    f = small_replay().frame(2)
    assert f.ambulances[0]["x"] == 2.0 and f.ambulances[0]["y"] == 1.0
    assert f.hospitals[0]["x"] == 9.0 and f.hospitals[0]["er_fraction"] == 0.25
    assert f.incidents[0]["victims"][0]["severity"] == 4
    assert small_replay().frame(99).minute == 3


def test_events_until_excludes_future_and_snapshots():
    r = small_replay()
    assert r.events_until(1) == []
    assert [e["kind"] for e in r.events_until(2)] == ["action_accepted"]


def test_feed_newest_first_and_unknown_kinds_hidden():
    events = [{"t": 1, "kind": "incident_arrived", "incident_id": "I", "victims": 2, "max_severity": 5},
              {"t": 1, "kind": "llm_call"},
              {"t": 2, "kind": "ambulance_on_scene", "ambulance_id": "A", "incident_id": "I"}]
    items = feed_items(events)
    assert [i.t for i in items] == [2, 1]
    assert to_feed_item({"t": 3, "kind": "never_heard_of_it"}) is None


def test_new_event_type_can_be_registered():
    @feed_event("hospital_counter_test", "hospital")
    def _fmt(e):
        return f"{e['hospital_id']} countered"
    item = to_feed_item({"t": 5, "kind": "hospital_counter_test", "hospital_id": "H-T"})
    assert item.category == "hospital" and item.text == "H-T countered"


def test_available_runs_only_lists_existing_logs(tmp_path):
    (tmp_path / "greedy").mkdir()
    (tmp_path / "greedy" / "normal_seed43_greedy.jsonl").write_text("")
    (tmp_path / "greedy" / "junk.txt").write_text("")
    runs = available_runs(tmp_path)
    assert [(r.scenario, r.seed, r.mode, r.run_number) for r in runs] == [("normal", 43, "greedy", 2)]


def test_real_log_replays_end_to_end():
    run = next(r for r in available_runs() if (r.scenario, r.seed, r.mode) == ("normal", 42, "negotiation"))
    replay = Replay.load(run)
    for minute in range(0, replay.last_minute + 1, 10):
        f = replay.frame(minute)
        assert len(f.ambulances) == 5 and len(f.hospitals) == 3
        assert all(0 <= a["x"] <= 20 and 0 <= a["y"] <= 20 for a in f.ambulances)
    assert any(i.category == "agent" for i in feed_items(replay.events_until(replay.last_minute)))
