"""The decision agents (OpenAI Agents SDK). The Assessment Agent lives in assessment.py.

Each round, the Dispatch Agent only receives the propose tools for resources that are
actually free, so it cannot propose units that do not exist or are busy.
"""
from __future__ import annotations

from agents import Agent

from erc.agents.context import AgentContext
from erc.agents.llm_cache import LLMResult, run_cached
from erc.agents.prompts import (
    DESTINATION_INSTRUCTIONS, DISPATCH_INSTRUCTIONS, HOSPITAL_INSTRUCTIONS, destination_prompt, dispatch_prompt,
    hospital_prompt,
)
from erc.agents.tools import (
    DESTINATION_TOOLS, DISPATCH_TOOLS, HOSPITAL_TOOLS, dispatch_situation, estimate_travel_minutes, hospital_situation,
    submit_ambulance_assignment, submit_team_assignment,
)
from erc.config import SETTINGS

DISPATCH_AGENT = Agent[AgentContext](name="DispatchAgent", model=SETTINGS.llm.model,
                                     instructions=DISPATCH_INSTRUCTIONS, tools=DISPATCH_TOOLS)
HOSPITAL_AGENT = Agent[AgentContext](name="HospitalCoordinationAgent", model=SETTINGS.llm.model,
                                     instructions=HOSPITAL_INSTRUCTIONS, tools=HOSPITAL_TOOLS)
# v2: Dispatch also requests the destination hospital (Hospital Coordination reviews it, see admission.py)
DESTINATION_AGENT = Agent[AgentContext](name="DispatchDestinationAgent", model=SETTINGS.llm.model,
                                        instructions=DESTINATION_INSTRUCTIONS, tools=DESTINATION_TOOLS)


def dispatch_agent_for(ctx: AgentContext) -> Agent:
    """The Dispatch Agent with only the tools usable this round."""
    view = dispatch_situation(ctx)
    tools = [estimate_travel_minutes]
    if view["free_ambulances"] and view["incidents"]:
        tools.append(submit_ambulance_assignment)
    if any(t["est_minutes_to"] for t in view["free_teams"]):
        tools.append(submit_team_assignment)
    return DISPATCH_AGENT.clone(tools=tools)


def needs_dispatch(ctx: AgentContext) -> bool:
    """True if some waiting victim could get an ambulance, or some team could be sent."""
    view = dispatch_situation(ctx)
    return any(i["nearest_free_ambulances"] for i in view["incidents"]) or \
        any(t["est_minutes_to"] for t in view["free_teams"])


def needs_hospital(ctx: AgentContext) -> bool:
    return bool(hospital_situation(ctx)["ambulances_needing_destination"])


async def run_dispatch(ctx: AgentContext) -> LLMResult | None:
    if not needs_dispatch(ctx):
        return None
    return await run_cached(dispatch_agent_for(ctx), dispatch_prompt(ctx), ctx)


async def run_hospital(ctx: AgentContext) -> LLMResult | None:
    return await run_cached(HOSPITAL_AGENT, hospital_prompt(ctx), ctx) if needs_hospital(ctx) else None


async def run_destination(ctx: AgentContext) -> LLMResult | None:
    return await run_cached(DESTINATION_AGENT, destination_prompt(ctx), ctx) if needs_hospital(ctx) else None
