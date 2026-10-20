"""Tests: agent wiring and prompts (no API calls)."""
from erc.agents.agents import DISPATCH_AGENT, HOSPITAL_AGENT, needs_dispatch, needs_hospital
from erc.agents.assessment import oracle_assessment
from erc.agents.context import AgentContext, state_fingerprint
from erc.agents.prompts import dispatch_prompt
from erc.models.state import SimulationState


def make_ctx(scenario):
    state = SimulationState.from_scenario(scenario)
    reports = {i.incident_id: oracle_assessment(i) for i in state.visible_incidents()}
    return AgentContext(state=state, assessments=reports, round_id="T0")


def test_agents_have_only_their_own_tools():
    assert {t.name for t in DISPATCH_AGENT.tools} == {
        "estimate_travel_minutes", "submit_ambulance_assignment", "submit_team_assignment"}
    assert {t.name for t in HOSPITAL_AGENT.tools} == {
        "hospital_status", "estimate_travel_minutes", "submit_admission", "submit_diversion"}


def test_prompt_carries_fingerprint_and_situation(tiny_scenario):
    ctx = make_ctx(tiny_scenario)
    prompt = dispatch_prompt(ctx)
    assert state_fingerprint(ctx.state) in prompt and '"incidents"' in prompt


def test_agents_only_called_when_needed(tiny_scenario):
    ctx = make_ctx(tiny_scenario)
    assert needs_dispatch(ctx) and not needs_hospital(ctx)
    ctx.state.reservations["V-01"] = "AMB-01"
    assert needs_hospital(ctx)