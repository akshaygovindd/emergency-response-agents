"""Tests: negotiation records list every conflict and admission negotiation with ordered steps and raw messages."""
import json

import pytest

from erc.dashboard.negotiations import is_notable, negotiation_records
from erc.dashboard.replay import LOGS_DIR


def msg(t, mid, mtype, sender, recipient, negotiation, round_=1, reply=None, action=None, incident="INC-01"):
    return {"t": t, "kind": "agent_message", "sender": sender, "recipient": recipient, "message_type": mtype,
            "incident_id": incident, "proposed_action": action, "message_id": mid, "reason": "because", "negotiation_id": negotiation,
            "round": round_, "in_reply_to": reply}


AMB = {"action_type": "assign_ambulance", "ambulance_id": "AMB-03", "victim_ids": ["V-1"]}


def conflict_events():
    return [
        {"t": 6, "kind": "conflict_detected", "conflict_id": "t006-C01", "conflict_type": "resource", "proposal_ids": ["P1", "P2"],
         "resources": ["ambulance:AMB-01"], "incident_ids": ["INC-01", "INC-02"], "reason": "2 proposals claim ambulance:AMB-01"},
        msg(6, "t006-M0007", "counter_proposal", "resource_allocation", "dispatch", "t006-C01", action=AMB),
        msg(6, "t006-M0008", "accept", "dispatch", "resource_allocation", "t006-C01", reply="t006-M0007", action=AMB),
        {"t": 6, "kind": "conflict_resolved", "conflict_id": "t006-C01", "method": "negotiation", "winners": ["P3"], "losers": ["P1"]},
    ]


def test_conflict_record_has_ordered_steps_and_raw_messages():
    (record,) = negotiation_records(conflict_events())
    assert record["kind"] == "conflict" and record["t"] == 6 and record["type"] == "Resource conflict"
    assert record["incidents"] == ["INC-01", "INC-02"] and record["units"] == ["AMB-01"]
    assert [s["label"] for s in record["steps"]] == ["Conflict detected", "Counter-offer", "Accept", "Resolved"]
    assert record["steps"][1]["raw"]["message_id"] == "t006-M0007" and record["steps"][1]["text"] == "send AMB-03 to INC-01 (V-1)"
    assert record["outcome"] == "Settled by negotiation" and record["rounds"] == 1


def test_rule_and_fallback_conflicts_have_no_message_steps():
    events = [conflict_events()[0], {"t": 6, "kind": "conflict_resolved", "conflict_id": "t006-C01", "method": "priority_rule",
                                     "winners": ["P1"], "losers": ["P2"]}]
    (record,) = negotiation_records(events)
    assert [s["label"] for s in record["steps"]] == ["Conflict detected", "Rule"] and "fixed priority rule" in record["outcome"]


def test_admission_record_with_reject_and_revised_outcome():
    adm = {"action_type": "admit_patient", "hospital_id": "H-B", "victim_ids": ["V-1"]}
    events = [msg(33, "M1", "proposal", "dispatch", "hospital_coordination", "ADM-t033-02", 1, action=adm, incident="INC-04"),
              msg(33, "M2", "reject", "hospital_coordination", "dispatch", "ADM-t033-02", 1, reply="M1", action=adm, incident="INC-04"),
              msg(33, "M3", "accept", "hospital_coordination", "dispatch", "ADM-t033-02", 2, action={**adm, "hospital_id": "H-G"}, incident="INC-04"),
              {"t": 33, "kind": "admission_resolved", "negotiation_id": "ADM-t033-02", "incident_id": "INC-04", "victim_ids": ["V-1"],
               "requested": "H-B", "hospital_id": "H-G", "method": "revised", "rounds": 2}]
    (record,) = negotiation_records(events)
    assert record["kind"] == "admission" and record["units"] == ["H-B", "H-G"] and record["rounds"] == 2
    assert [s["label"] for s in record["steps"]] == ["Proposal", "Reject", "Accept", "Outcome"]
    assert record["steps"][-1]["raw"]["method"] == "revised" and is_notable(record)


def test_plain_first_try_admission_is_not_notable():
    done = {"t": 7, "kind": "admission_resolved", "negotiation_id": "ADM-t007-01", "incident_id": "INC-02", "victim_ids": ["V-2"],
            "requested": "H-T", "hospital_id": "H-T", "method": "accepted", "rounds": 1}
    (record,) = negotiation_records([done])
    assert not is_notable(record) and record["units"] == ["H-T"]


def test_real_runs_list_every_logged_negotiation():
    path = LOGS_DIR / "v2" / "negotiation" / "normal_seed42_negotiation.jsonl"
    if not path.exists():
        pytest.skip("saved v2 run not available")
    events = [json.loads(line) for line in path.read_text().splitlines() if line]
    records = negotiation_records(events)
    assert len([r for r in records if r["kind"] == "conflict"]) == sum(e["kind"] == "conflict_detected" for e in events)
    assert len([r for r in records if r["kind"] == "admission"]) == sum(e["kind"] == "admission_resolved" for e in events)
    assert [r["t"] for r in records] == sorted(r["t"] for r in records)
    in_steps = {s["id"] for r in records for s in r["steps"]}
    assert all(e["message_id"] in in_steps for e in events if e["kind"] == "agent_message" and e.get("negotiation_id"))
    v1 = LOGS_DIR / "v1" / "agents" / "normal_seed42_agents.jsonl"
    if v1.exists():
        rule = negotiation_records([json.loads(line) for line in v1.read_text().splitlines() if line])
        assert rule and all(r["method"] == "priority_rule" for r in rule)
