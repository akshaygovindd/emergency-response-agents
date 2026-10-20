"""Tests: tools must show assessments (never truth), catch invented IDs, and pool proposals."""
import json

from erc.agents import tools as T
from erc.agents.assessment import oracle_assessment
from erc.agents.context import AgentContext
from erc.models.entities import Severity
from erc.models.state import SimulationState


def make_ctx(scenario, time=0):
    state = SimulationState.from_scenario(scenario)
    state.time_min = time
    reports = {i.incident_id: oracle_assessment(i) for i in state.visible_incidents()}
    return AgentContext(state=state, assessments=reports, round_id=f"T{time}")


def test_dispatch_view_uses_assessments_not_truth(tiny_scenario):
    ctx = make_ctx(tiny_scenario)
    ctx.assessments["INC-01"].victims[0].severity = Severity.MODERATE   # truth is 5
    view = T.dispatch_situation(ctx)
    assert view["incidents"][0]["waiting_victims"][0]["urgency"] == 2
    text = json.dumps(view)
    assert "deadline" not in text and "condition" not in text


def test_valid_proposal_enters_pool(tiny_scenario):
    ctx = make_ctx(tiny_scenario)
    msg = T.propose_ambulance(ctx, "AMB-01", "INC-01", ["V-01"], 1, "critical trauma")
    assert msg.startswith("ACCEPTED") and ctx.proposals[0].proposal_id == "T0-P01"


def test_invented_id_is_rejected_and_counted(tiny_scenario):
    ctx = make_ctx(tiny_scenario)
    msg = T.propose_ambulance(ctx, "AMB-99", "INC-01", ["V-01"], 1, "x")
    assert msg.startswith("REJECTED") and not ctx.proposals
    assert ctx.invalid[0]["reason"] == "unknown_resource"


def test_duplicates_are_not_added_twice(tiny_scenario):
    ctx = make_ctx(tiny_scenario)
    for _ in range(2):
        T.propose_ambulance(ctx, "AMB-01", "INC-01", ["V-01"], 1, "x")
    assert len(ctx.proposals) == 1


def test_pool_holds_conflicting_proposals(tiny_scenario):
    ctx = make_ctx(tiny_scenario, time=10)
    T.propose_ambulance(ctx, "AMB-01", "INC-01", ["V-01"], 1, "a")
    T.propose_ambulance(ctx, "AMB-01", "INC-02", ["V-02"], 2, "b")
    assert len(ctx.proposals) == 2      # both valid alone; the conflict is resolved later


def test_admission_needs_dispatched_victims(tiny_scenario):
    ctx = make_ctx(tiny_scenario)
    assert T.propose_admission(ctx, "H-T", ["V-01"], "x").startswith("REJECTED")
    ctx.state.reservations["V-01"] = "AMB-01"
    assert T.propose_admission(ctx, "H-T", ["V-01"], "x").startswith("ACCEPTED")
    assert ctx.proposals[0].priority == 1     # urgency 5 -> priority 1


def test_hospital_view_lists_only_capable_destinations(tiny_scenario):
    ctx = make_ctx(tiny_scenario)
    ctx.state.reservations["V-01"] = "AMB-01"
    amb = T.hospital_situation(ctx)["ambulances_needing_destination"][0]
    assert set(amb["est_minutes_to"]) == {"H-T"}    # only the Trauma Center treats trauma


def test_snapshot_and_restore(tiny_scenario):
    ctx = make_ctx(tiny_scenario)
    T.propose_ambulance(ctx, "AMB-01", "INC-01", ["V-01"], 1, "x")
    T.propose_ambulance(ctx, "AMB-99", "INC-01", ["V-01"], 1, "x")
    fresh = make_ctx(tiny_scenario)
    fresh.restore(ctx.snapshot_since(0, 0))
    assert fresh.proposals == ctx.proposals and fresh.invalid == ctx.invalid


def test_travel_tool_hides_future_incidents(tiny_scenario):
    ctx = make_ctx(tiny_scenario, time=0)
    assert "Unknown" in T.travel_minutes(ctx, "AMB-01", "INC-02")   # INC-02 arrives at minute 10