"""Tests: conflict detection must be pure and complete; the priority rule must be deterministic."""
from erc.agents import tools as T
from erc.agents.assessment import oracle_assessment
from erc.agents.conflicts import ConflictType, detect_conflicts, resolve_by_priority
from erc.agents.context import AgentContext
from erc.models.state import SimulationState


def make_ctx(scenario, time=0):
    state = SimulationState.from_scenario(scenario)
    state.time_min = time
    reports = {i.incident_id: oracle_assessment(i) for i in state.visible_incidents()}
    return AgentContext(state=state, assessments=reports, round_id=f"T{time}")


def test_two_incidents_claiming_one_ambulance(tiny_scenario):
    ctx = make_ctx(tiny_scenario, 10)
    T.propose_ambulance(ctx, "AMB-01", "INC-01", ["V-01"], 1, "a")
    T.propose_ambulance(ctx, "AMB-01", "INC-02", ["V-02"], 2, "b")
    [c] = detect_conflicts(ctx.proposals, ctx.state)
    assert c.conflict_type == ConflictType.RESOURCE and c.resources == ["ambulance:AMB-01"]


def test_one_victim_claimed_twice(tiny_scenario):
    ctx = make_ctx(tiny_scenario)
    T.propose_ambulance(ctx, "AMB-01", "INC-01", ["V-01"], 1, "a")
    T.propose_ambulance(ctx, "AMB-02", "INC-01", ["V-01"], 1, "b")
    [c] = detect_conflicts(ctx.proposals, ctx.state)
    assert c.resources == ["victim:V-01"]


def test_disjoint_proposals_do_not_conflict(tiny_scenario):
    ctx = make_ctx(tiny_scenario, 10)
    T.propose_ambulance(ctx, "AMB-01", "INC-01", ["V-01"], 1, "a")
    T.propose_ambulance(ctx, "AMB-02", "INC-02", ["V-02"], 2, "b")
    assert detect_conflicts(ctx.proposals, ctx.state) == []


def make_capacity_conflict(scenario):
    ctx = make_ctx(scenario, 10)
    ctx.state.hospitals["H-T"].er_occupied = 3          # room for one more
    ctx.state.reservations.update({"V-01": "AMB-01", "V-02": "AMB-02"})
    T.propose_admission(ctx, "H-T", ["V-02"], "a")      # severity 3, proposed first
    T.propose_admission(ctx, "H-T", ["V-01"], "b")      # severity 5
    return ctx


def test_capacity_conflict_detected(tiny_scenario):
    ctx = make_capacity_conflict(tiny_scenario)
    [c] = detect_conflicts(ctx.proposals, ctx.state)
    assert c.conflict_type == ConflictType.CAPACITY and c.resources == ["er:H-T"]


def test_priority_rule_prefers_higher_severity(tiny_scenario):
    ctx = make_ctx(tiny_scenario, 10)
    T.propose_ambulance(ctx, "AMB-01", "INC-02", ["V-02"], 1, "severity 3")
    T.propose_ambulance(ctx, "AMB-01", "INC-01", ["V-01"], 1, "severity 5")
    [c] = detect_conflicts(ctx.proposals, ctx.state)
    assert resolve_by_priority(c, ctx) == ["T10-P02"]


def test_capacity_rule_keeps_most_urgent(tiny_scenario):
    ctx = make_capacity_conflict(tiny_scenario)
    [c] = detect_conflicts(ctx.proposals, ctx.state)
    assert resolve_by_priority(c, ctx) == ["T10-P02"]   # the severity-5 admission


def test_ties_break_by_proposal_id(tiny_scenario):
    ctx = make_ctx(tiny_scenario)
    T.propose_ambulance(ctx, "AMB-02", "INC-01", ["V-01"], 1, "a")
    T.propose_ambulance(ctx, "AMB-01", "INC-01", ["V-01"], 1, "b")
    [c] = detect_conflicts(ctx.proposals, ctx.state)
    assert resolve_by_priority(c, ctx) == ["T0-P01"]


def test_detector_is_pure(tiny_scenario):
    ctx = make_capacity_conflict(tiny_scenario)
    before_state, before_pool = ctx.state.model_dump(), [p.model_dump() for p in ctx.proposals]
    detect_conflicts(ctx.proposals, ctx.state)
    assert ctx.state.model_dump() == before_state and [p.model_dump() for p in ctx.proposals] == before_pool