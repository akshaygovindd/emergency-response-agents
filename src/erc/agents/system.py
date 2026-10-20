"""The multi-agent system as a policy the engine can run.

Each decision round:
  assess new incidents -> Dispatch and Hospital propose (via tools) -> Python detects conflicts
  -> conflicts are resolved -> COMMIT messages -> Decisions for the engine, which validates again.
In this system Resource Allocation resolves conflicts with the fixed priority rule; the
negotiating system (negotiation.py) replaces that step with negotiation.
"""
from __future__ import annotations

import asyncio

from erc.agents.agents import run_dispatch, run_hospital
from erc.agents.assessment import ASSESSMENT_AGENT, oracle_assessment, to_report
from erc.agents.conflicts import Conflict, detect_conflicts, resolve_by_priority
from erc.agents.context import AgentContext
from erc.agents.llm_cache import LLMResult, run_cached
from erc.logging.event_log import EventLog
from erc.models.messages import AgentMessage, AgentName, MessageType, ProposedAction
from erc.models.state import SimulationState
from erc.scenarios.descriptions import load_descriptions
from erc.sim.engine import Decision

RA = AgentName.RESOURCE_ALLOCATION

# One event loop for the whole program: the OpenAI client keeps its connections tied to the
# loop that created them, so every agent system (and every run) must share the same loop.
_LOOP: asyncio.AbstractEventLoop | None = None


def shared_loop() -> asyncio.AbstractEventLoop:
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
    return _LOOP


class AgentSystem:
    def __init__(self, negotiate: bool = False, oracle: bool = False) -> None:
        self.negotiate, self.oracle = negotiate, oracle
        self.name = "oracle" if oracle else ("negotiation" if negotiate else "agents")
        self.log: EventLog | None = None
        self.assessments: dict = {}
        self._texts: dict[str, str] | None = None
        self._n_messages = 0
        self._proposal_msg: dict[str, str] = {}

    def bind_log(self, log: EventLog) -> None:
        self.log = log

    def decide(self, state: SimulationState) -> list[Decision]:
        return shared_loop().run_until_complete(self._decide(state))

    # ───────── One decision round ─────────
    async def _decide(self, state: SimulationState) -> list[Decision]:
        t, round_id = state.time_min, f"t{state.time_min:03d}"
        await self._assess_new(state)
        ctx = AgentContext(state=state, assessments=self.assessments, round_id=round_id)

        for role, runner in ((AgentName.DISPATCH, run_dispatch), (AgentName.HOSPITAL, run_hospital)):
            n_prop, n_inv = len(ctx.proposals), len(ctx.invalid)
            res = await runner(ctx)
            if res is not None:
                self._log_llm(t, role, res)
            for p in ctx.proposals[n_prop:]:
                self._proposal_msg[p.proposal_id] = self._message(
                    t, role, RA, MessageType.PROPOSAL, p.incident_id, p.action, p.priority, p.reason)
            for bad in ctx.invalid[n_inv:]:
                self._record(t, "proposal_invalid", agent=role.value, **bad)

        chosen = {p.proposal_id for p in ctx.proposals}
        for conflict in detect_conflicts(ctx.proposals, state, round_id):
            self._record(t, "conflict_detected", **conflict.model_dump(mode="json"))
            winners, method = await self._resolve(conflict, ctx, chosen)
            losers = [pid for pid in conflict.proposal_ids if pid not in winners]
            chosen -= set(losers)
            chosen |= set(winners)          # may include counter-proposals created by negotiation
            by_id = {p.proposal_id: p for p in ctx.proposals}
            nid = conflict.conflict_id if method == "negotiation" else None
            for pid in conflict.proposal_ids:
                p = by_id[pid]
                verdict = MessageType.ACCEPT if pid in winners else MessageType.REJECT
                self._message(t, RA, p.proposer, verdict, p.incident_id, p.action, p.priority,
                              f"{method}: {conflict.reason}", in_reply_to=self._proposal_msg.get(pid, pid),
                              negotiation_id=nid, round_=1 if nid else 0)
            self._record(t, "conflict_resolved", conflict_id=conflict.conflict_id, method=method,
                         winners=sorted(winners), losers=sorted(losers))

        decisions = []
        for p in ctx.proposals:
            if p.proposal_id in chosen:
                mid = self._message(t, RA, p.proposer, MessageType.COMMIT, p.incident_id, p.action,
                                    p.priority, "Committed for final validation")
                decisions.append(Decision(p.action, p.incident_id, source=p.proposer.value, message_id=mid))
        return decisions

    async def _resolve(self, conflict: Conflict, ctx: AgentContext, chosen: set[str]) -> tuple[list[str], str]:
        """Fixed priority rule. The negotiating system overrides this step."""
        return resolve_by_priority(conflict, ctx), "priority_rule"

    # ───────── Assessment ─────────
    async def _assess_new(self, state: SimulationState) -> None:
        t = state.time_min
        new = [i for i in state.visible_incidents() if i.incident_id not in self.assessments]
        if not new:
            return
        if self.oracle:
            reports = {i.incident_id: oracle_assessment(i) for i in new}
        else:
            if self._texts is None:
                self._texts = load_descriptions(state.scenario_name, state.seed)
            results = await asyncio.gather(*(run_cached(ASSESSMENT_AGENT, f"Dispatch report:\n{self._texts[i.incident_id]}")
                                             for i in new))
            reports = {}
            for inc, res in zip(new, results):
                self._log_llm(t, AgentName.ASSESSMENT, res)
                try:
                    reports[inc.incident_id] = to_report(inc, res.output)
                except ValueError as e:
                    self._record(t, "assessment_failed", incident_id=inc.incident_id, detail=str(e))
        for iid, rep in reports.items():
            self.assessments[iid] = rep
            self._record(t, "assessment", incident_id=iid,
                         victims=[[v.victim_id, int(v.severity), v.required_capability.value] for v in rep.victims])
            self._message(t, AgentName.ASSESSMENT, AgentName.DISPATCH, MessageType.INFO, iid, None,
                          6 - int(rep.max_severity), rep.reasoning)

    # ───────── Logging helpers ─────────
    def _record(self, t: int, kind: str, **data) -> None:
        if self.log is not None:
            self.log.record(t, kind, **data)

    def _log_llm(self, t: int, agent: AgentName, res: LLMResult) -> None:
        self._record(t, "llm_call", agent=agent.value, tokens_in=res.tokens_in, tokens_out=res.tokens_out,
                     latency_s=res.latency_s, cache_hit=res.cache_hit, requests=res.requests)

    def _message(self, t: int, sender: AgentName, recipient: AgentName, mtype: MessageType, incident_id: str,
                 action: ProposedAction | None, priority: int, reason: str, in_reply_to: str | None = None,
                 negotiation_id: str | None = None, round_: int = 0) -> str:
        self._n_messages += 1
        mid = f"t{t:03d}-M{self._n_messages:04d}"
        msg = AgentMessage(sender=sender, recipient=recipient, message_type=mtype, incident_id=incident_id,
                           proposed_action=action, message_id=mid, timestamp_min=t,
                           priority=min(5, max(1, int(priority))), reason=(reason or "-")[:500],
                           in_reply_to=in_reply_to, negotiation_id=negotiation_id, round=round_)
        self._record(t, "agent_message", **msg.model_dump(mode="json"))
        return mid