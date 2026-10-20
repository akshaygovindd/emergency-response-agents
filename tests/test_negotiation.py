"""Tests: negotiation reallocates losers safely and falls back on bad answers (no API calls)."""
import asyncio

from erc.agents import negotiation as N
from erc.agents import tools as T
from erc.agents.assessment import oracle_assessment
from erc.agents.conflicts import detect_conflicts
from erc.agents.context import AgentContext
from erc.agents.llm_cache import LLMResult
from erc.models.state import SimulationState


def answer(output):
    return LLMResult(output, 0, 0, 0.0, False, 1)


def two_incidents_one_ambulance(scenario):
    state = SimulationState.from_scenario(scenario)
    state.time_min = 10
    reports = {i.incident_id: oracle_assessment(i) for i in state.visible_incidents()}
    ctx = AgentContext(state=state, assessments=reports, round_id="T10")
    T.propose_ambulance(ctx, "AMB-01", "INC-01", ["V-01"], 1, "a")   # T10-P01, severity 5
    T.propose_ambulance(ctx, "AMB-01", "INC-02", ["V-02"], 2, "b")   # T10-P02, severity 3
    [conflict] = detect_conflicts(ctx.proposals, ctx.state, "T10")
    return ctx, conflict


def resolve(conflict, ctx):
    chosen = {p.proposal_id for p in ctx.proposals}
    return asyncio.run(N.NegotiatingSystem()._resolve(conflict, ctx, chosen))


def test_negotiation_gives_loser_another_ambulance(tiny_scenario, monkeypatch):
    async def ra(prompt):
        return answer({"winner_proposal_ids": ["T10-P01"], "reasoning": "x", "counter_proposals": [
            {"for_proposal_id": "T10-P02", "alternative_id": "AMB-02", "reason": "next closest"}]})

    async def proposer(who, prompt):
        return answer({"decision": "accept", "suggested_alternative_id": "none", "reason": "fine"})

    monkeypatch.setattr(N, "ask_resource_allocation", ra)
    monkeypatch.setattr(N, "ask_proposer", proposer)
    ctx, conflict = two_incidents_one_ambulance(tiny_scenario)
    winners, method = resolve(conflict, ctx)
    assert method == "negotiation" and winners[0] == "T10-P01" and len(winners) == 2
    counter = next(p for p in ctx.proposals if p.proposal_id == winners[1])
    assert counter.action.ambulance_id == "AMB-02" and counter.action.victim_ids == ["V-02"]


def test_counter_with_claimed_ambulance_is_refused(tiny_scenario, monkeypatch):
    async def ra(prompt):
        return answer({"winner_proposal_ids": ["T10-P01"], "reasoning": "x", "counter_proposals": [
            {"for_proposal_id": "T10-P02", "alternative_id": "AMB-01", "reason": "same unit"}]})

    monkeypatch.setattr(N, "ask_resource_allocation", ra)
    ctx, conflict = two_incidents_one_ambulance(tiny_scenario)
    winners, method = resolve(conflict, ctx)
    assert winners == ["T10-P01"] and method == "negotiation"


def test_broken_resolution_falls_back_to_priority_rule(tiny_scenario, monkeypatch):
    async def ra(prompt):
        return answer({"winner_proposal_ids": ["NOPE"], "counter_proposals": [], "reasoning": "x"})

    monkeypatch.setattr(N, "ask_resource_allocation", ra)
    ctx, conflict = two_incidents_one_ambulance(tiny_scenario)
    assert resolve(conflict, ctx) == (["T10-P01"], "fallback")