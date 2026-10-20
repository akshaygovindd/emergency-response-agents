"""The decision agents (OpenAI Agents SDK). The Assessment Agent lives in assessment.py."""
from __future__ import annotations

from agents import Agent

from erc.agents.context import AgentContext
from erc.agents.llm_cache import LLMResult, run_cached
from erc.agents.prompts import DISPATCH_INSTRUCTIONS, HOSPITAL_INSTRUCTIONS, dispatch_prompt, hospital_prompt
from erc.agents.tools import DISPATCH_TOOLS, HOSPITAL_TOOLS, dispatch_situation, hospital_situation
from erc.config import SETTINGS

DISPATCH_AGENT = Agent[AgentContext](name="DispatchAgent", model=SETTINGS.llm.model,
                                     instructions=DISPATCH_INSTRUCTIONS, tools=DISPATCH_TOOLS)
HOSPITAL_AGENT = Agent[AgentContext](name="HospitalCoordinationAgent", model=SETTINGS.llm.model,
                                     instructions=HOSPITAL_INSTRUCTIONS, tools=HOSPITAL_TOOLS)


def needs_dispatch(ctx: AgentContext) -> bool:
    """True if some waiting victim could get an ambulance, or some team could be sent."""
    view = dispatch_situation(ctx)
    return any(i["nearest_free_ambulances"] for i in view["incidents"]) or \
        any(t["est_minutes_to"] for t in view["free_teams"])


def needs_hospital(ctx: AgentContext) -> bool:
    return bool(hospital_situation(ctx)["ambulances_needing_destination"])


async def run_dispatch(ctx: AgentContext) -> LLMResult | None:
    return await run_cached(DISPATCH_AGENT, dispatch_prompt(ctx), ctx) if needs_dispatch(ctx) else None


async def run_hospital(ctx: AgentContext) -> LLMResult | None:
    return await run_cached(HOSPITAL_AGENT, hospital_prompt(ctx), ctx) if needs_hospital(ctx) else None