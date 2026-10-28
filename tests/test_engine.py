"""Tests: the engine must move the world correctly, fairly, and cheaply."""
from erc.models.entities import VictimStatus
from erc.models.messages import ActionType, ProposedAction
from erc.policies.naive import NaivePolicy
from erc.sim.engine import Decision, Engine


class IdlePolicy:
    name = "idle"

    def decide(self, state):
        return []


class BrokenPolicy:
    name = "broken"

    def decide(self, state):
        action = ProposedAction(action_type=ActionType.ASSIGN_AMBULANCE, ambulance_id="AMB-99",
                                victim_ids=["V-01"])
        return [Decision(action, "INC-01", source=self.name)]


def run(scenario, policy):
    engine = Engine(scenario, policy)
    engine.run()
    return engine


def test_naive_gets_critical_victim_treated(tiny_scenario):
    e = run(tiny_scenario, NaivePolicy())
    assert e.state.find_victim("V-01").status == VictimStatus.TREATED
    assert e.state.first_contact_min["V-01"] < e.state.treatment_start_min["V-01"]


def test_fire_team_used_and_no_staff_means_no_treatment(tiny_scenario):
    e = run(tiny_scenario, NaivePolicy())
    assert any(ev["kind"] == "responder_arrived" and ev["team_id"] == "FIRE-1" for ev in e.log.events)
    # V-02 reaches General Hospital, which has no staff in this tiny scenario
    assert e.state.find_victim("V-02").status == VictimStatus.AWAITING_TREATMENT


def test_invalid_actions_rejected_and_logged(tiny_scenario):
    e = run(tiny_scenario, BrokenPolicy())
    rejected = e.log.of_kind("action_rejected")
    assert rejected and rejected[0]["reason"] == "unknown_resource"
    assert e.state.find_victim("V-01").status == VictimStatus.UNSERVED


def test_runs_are_deterministic(tiny_scenario):
    assert run(tiny_scenario, NaivePolicy()).log.events == run(tiny_scenario, NaivePolicy()).log.events


def test_policy_only_called_when_something_changes(tiny_scenario):
    assert run(tiny_scenario, IdlePolicy()).policy_calls <= 3


def test_scenario_untouched_after_run(tiny_scenario):
    run(tiny_scenario, NaivePolicy())
    assert all(v.status == VictimStatus.WAITING for i in tiny_scenario.incidents for v in i.victims)

def test_snapshot_has_replay_fields(tiny_scenario):
    snaps = run(tiny_scenario, NaivePolicy()).log.of_kind("snapshot")
    first, busy = snaps[0], next(s for s in snaps if s["incidents"] and s["ambulances"][0]["status"] != "available")
    assert {a["id"] for a in first["ambulances"]} == {"AMB-01", "AMB-02"}
    assert set(first["ambulances"][0]) == {"id", "x", "y", "status", "target", "onboard"}
    assert set(first["responders"][0]) == {"id", "x", "y", "status", "target"}
    assert set(first["hospitals"][0]) == {"id", "er_occupied", "er_capacity",
                                          "treatment_in_use", "treatment_slots"}
    assert first["incidents"] == [] or "victims" in first["incidents"][0]
    incident = busy["incidents"][0]
    assert set(incident) == {"id", "x", "y", "victims"}
    assert set(incident["victims"][0]) == {"id", "severity", "status"}
    assert busy["ambulances"][0]["target"] is not None
    assert all(round(a["x"], 2) == a["x"] for s in snaps for a in s["ambulances"])
