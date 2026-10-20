"""Run one Dispatch round and one Hospital round on a frozen scenario moment and print the pool.

Usage:
    python scripts/probe_agents.py --scenario bottleneck --seed 42 --minute 7
"""
from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv

from erc.agents.agents import run_dispatch, run_hospital
from erc.agents.assessment import ASSESSMENT_AGENT, to_report
from erc.agents.context import AgentContext
from erc.agents.llm_cache import LLMResult, run_cached
from erc.config import SCENARIO_DIR, ScenarioName
from erc.models.entities import UnitStatus
from erc.models.messages import ActionType
from erc.models.state import Scenario, SimulationState
from erc.scenarios.descriptions import load_descriptions


def show(title: str, ctx: AgentContext, res: LLMResult | None, start: int, start_invalid: int) -> None:
    print(f"\n=== {title} ===")
    if res is None:
        print("  (nothing to decide)")
        return
    for p in ctx.proposals[start:]:
        a = p.action
        what = {ActionType.ASSIGN_AMBULANCE: f"{a.ambulance_id} -> {p.incident_id} {a.victim_ids}",
                ActionType.ASSIGN_RESPONDER: f"{a.responder_id} -> {p.incident_id}",
                ActionType.ADMIT_PATIENT: f"admit {a.victim_ids} -> {a.hospital_id}",
                ActionType.DIVERT_PATIENT: f"divert {a.victim_ids} -> {a.hospital_id}"}[a.action_type]
        print(f"  {p.proposal_id} | priority {p.priority} | {what}")
        print(f"      reason: {p.reason}")
    for bad in ctx.invalid[start_invalid:]:
        print(f"  REJECTED {bad['tool']} {bad['args']} -> {bad['reason']}: {bad['detail']}")
    print(f"  summary: {res.output}")
    print(f"  tokens in {res.tokens_in} | out {res.tokens_out} | model calls {res.requests} | "
          f"{res.latency_s:.1f}s | cache hit {res.cache_hit}")


async def main(name: ScenarioName, seed: int, minute: int) -> None:
    state = SimulationState.from_scenario(Scenario.load(SCENARIO_DIR / f"{name.value}_seed{seed}.json"))
    state.time_min = minute
    texts = load_descriptions(name, seed)
    assessments = {}
    for inc in state.visible_incidents():
        res = await run_cached(ASSESSMENT_AGENT, f"Dispatch report:\n{texts[inc.incident_id]}")
        assessments[inc.incident_id] = to_report(inc, res.output)
    ctx = AgentContext(state=state, assessments=assessments, round_id=f"PROBE-{minute}")
    print(f"{name.value} seed {seed}, minute {minute}: {len(assessments)} incidents visible, "
          f"{len(state.available_ambulances())} free ambulances")

    d = await run_dispatch(ctx)
    show("Dispatch Agent", ctx, d, 0, 0)

    # For probing only: pretend the first proposal per ambulance executed, so Hospital has work
    for p in ctx.proposals:
        if p.action.action_type == ActionType.ASSIGN_AMBULANCE:
            amb = state.ambulances[p.action.ambulance_id]
            if amb.is_available:
                amb.status = UnitStatus.EN_ROUTE
                amb.assigned_incident = p.incident_id
                for vid in p.action.victim_ids:
                    state.reservations[vid] = amb.ambulance_id
    n_prop, n_inv = len(ctx.proposals), len(ctx.invalid)
    h = await run_hospital(ctx)
    show("Hospital Coordination Agent", ctx, h, n_prop, n_inv)


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="bottleneck", choices=[s.value for s in ScenarioName])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--minute", type=int, default=7)
    args = parser.parse_args()
    asyncio.run(main(ScenarioName(args.scenario), args.seed, args.minute))