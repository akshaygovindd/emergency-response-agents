"""Tests: live utilization and the agent status panel are computed from the log, and match the results table."""
import json

import pytest

from erc.dashboard.agent_status import agent_status_by_minute, has_agents
from erc.dashboard.export import export_replay
from erc.dashboard.live import utilization_by_minute
from erc.dashboard.replay import LOGS_DIR, ROOT

RESULTS = ROOT / "results" / "v1" / "runs.jsonl"


def msg(t, sender, recipient, mtype, negotiation_id=None, incident="INC-01", action=None, mid="m"):
    return {"t": t, "kind": "agent_message", "sender": sender, "recipient": recipient, "message_type": mtype,
            "negotiation_id": negotiation_id, "incident_id": incident, "proposed_action": action, "message_id": mid,
            "reason": ""}


ASSIGN = {"action_type": "assign_ambulance", "ambulance_id": "AMB-01", "responder_id": None, "hospital_id": None,
          "victim_ids": ["V-01"]}


def small_log():
    return [
        {"t": 1, "kind": "incident_arrived", "incident_id": "INC-01"},
        msg(1, "incident_assessment", "dispatch", "info"),
        msg(1, "dispatch", "resource_allocation", "proposal", action=ASSIGN),
        msg(3, "resource_allocation", "dispatch", "commit", action=ASSIGN),
        msg(4, "dispatch", "resource_allocation", "counter_proposal", "t004-C01", action=ASSIGN),
        {"t": 3, "kind": "action_accepted", "incident_id": "INC-01", "message_id": "x", "source": "dispatch",
         "action": ASSIGN},
    ]


def test_status_idle_working_negotiating_and_last_action():
    frames = agent_status_by_minute(small_log(), {}, [{"H": 0}] * 6, 5)
    assessment, dispatch, _, allocation = frames[1]
    assert (assessment["status"], dispatch["status"], allocation["status"]) == ("working", "working", "idle")
    assert frames[0][0]["status"] == "idle" and frames[0][0]["last"] is None
    assert frames[4][1]["status"] == "negotiating" and "Suggested instead" in frames[4][1]["last"]
    assert frames[2][0]["status"] == "idle" and frames[2][0]["last"] == "Assessed Incident 1"


def test_pending_counts_open_work_until_it_is_resolved():
    frames = agent_status_by_minute(small_log(), {}, [{"H": 0}] * 6, 5)
    pending = lambda t, i: dict(frames[t][i]["pending"])
    assert pending(1, 1)["incidents awaiting a unit"] == 1 and pending(3, 1)["incidents awaiting a unit"] == 0
    assert pending(1, 3)["proposals awaiting a decision"] == 1 and pending(3, 3)["proposals awaiting a decision"] == 0
    assert pending(0, 0)["reports not yet assessed"] == 0


def test_rule_based_runs_have_no_agents():
    assert not has_agents([{"t": 0, "kind": "snapshot"}]) and has_agents(small_log())


@pytest.mark.skipif(not RESULTS.exists(), reason="saved results not present")
@pytest.mark.parametrize("mode", ["naive", "greedy", "agents", "negotiation"])
def test_last_minute_utilization_equals_the_results_table(mode):
    rows = {json.loads(line)["run_id"]: json.loads(line) for line in RESULTS.read_text().splitlines() if line}
    bundle = export_replay("v1", "normal", 42, mode)
    final = bundle["frames"][-1]["u"]
    row = rows[f"normal_seed42_{mode}"]
    assert final["amb"]["avg"] == pytest.approx(row["ambulance_utilization"], abs=1e-4)
    assert final["teams"]["avg"] == pytest.approx(row["responder_utilization"], abs=1e-4)
    assert set(final) == {"amb", "teams", "doctors", "nurses", "er"}
    assert all(0 <= f["u"][k]["now"] <= 1 for f in bundle["frames"] for k in f["u"])
    assert ("ag" in bundle["frames"][5]) == (mode in ("agents", "negotiation"))
    assert len(bundle["frames"][5].get("ag", [None] * 4)) == 4
