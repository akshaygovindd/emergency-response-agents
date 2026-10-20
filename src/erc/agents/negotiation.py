"""Negotiation: the Resource Allocation Agent resolves conflicts, and proposers can push back.

Protocol per conflict (max 3 rounds; the fixed priority rule is the fallback):
  round 1  Resource Allocation (LLM) picks winners and may offer each loser a counter-proposal
           built only from resources nobody has claimed.
  round 2  The losing proposer (Dispatch or Hospital, LLM) accepts the counter-proposal or rejects
           it, optionally suggesting another unclaimed alternative.
  round 3  Resource Allocation (LLM) accepts or denies that suggestion.
Every counter-proposal is checked by the validator and against claimed resources before it can be
committed, so negotiation can never produce an impossible action.
"""
from __future__ import annotations

import json
from typing import Literal

from agents import Agent
from pydantic import BaseModel, Field, ValidationError

from erc.agents.conflicts import Conflict, ConflictType, claimed_keys, resolve_by_priority
from erc.agents.context import AgentContext, Proposal, state_fingerprint
from erc.agents.llm_cache import LLMResult, run_cached
from erc.agents.system import RA, AgentSystem
from erc.agents.tools import _hospital_view, _victim_view, estimated_minutes
from erc.config import SETTINGS
from erc.models.entities import AmbulanceType, VictimStatus
from erc.models.messages import ActionType, AgentName, MessageType, ProposedAction
from erc.sim.validator import validate


# ───────── Structured outputs ─────────
class Counter(BaseModel):
    for_proposal_id: str
    alternative_id: str = Field(description="An unclaimed ambulance ID (ambulance conflicts) or hospital ID (hospital conflicts)")
    reason: str


class Resolution(BaseModel):
    winner_proposal_ids: list[str]
    counter_proposals: list[Counter]
    reasoning: str


class Reply(BaseModel):
    decision: Literal["accept", "reject"]
    suggested_alternative_id: str = Field(description="Another unclaimed ambulance or hospital ID you would accept, or 'none'")
    reason: str


class FinalCall(BaseModel):
    decision: Literal["accept", "deny"]
    reason: str


# ───────── Agents ─────────
RA_INSTRUCTIONS = """You are the Resource Allocation Agent in an emergency coordination center.
You see one conflict: proposals that cannot all execute together.
Objective: maximise the number of urgency 4-5 victims reached in time across the WHOLE system.

Decide:
- winner_proposal_ids: proposals that can execute together (no shared ambulance, team, or victim;
  for hospital conflicts, the winners' victims must fit the hospital's remaining ER room).
- For each losing proposal you may add ONE counter_proposal that uses an ID from unclaimed_alternatives
  (never a contested or claimed resource). Offer one only if it still helps that incident; otherwise omit it.
- Weigh urgency, minutes already waited, and travel minutes. Usually the contested unit should go where it
  reaches the most urgent victims fastest, and the other incident should get the next best unit.
Use only IDs shown in the conflict. Explain your reasoning in one or two sentences."""

DISPATCH_NEGOTIATOR_INSTRUCTIONS = """You are the Dispatch Agent negotiating for one incident.
Resource Allocation rejected your proposal and offers a counter-proposal instead.
Accept it if it still gets these victims timely care. Reject it only if it is clearly worse than waiting
for another unit; if you reject, you may suggest another ID from unclaimed_alternatives, otherwise 'none'.
Reply in one short sentence of reasoning."""

HOSPITAL_NEGOTIATOR_INSTRUCTIONS = """You are the Hospital Coordination Agent negotiating for one ambulance.
Resource Allocation rejected your admission and offers a different hospital instead.
Accept it if that hospital can treat the patients without being overloaded. Reject it only if it is clearly
worse; if you reject, you may suggest another hospital ID from unclaimed_alternatives, otherwise 'none'.
Reply in one short sentence of reasoning."""

RA_FINAL_INSTRUCTIONS = """You are the Resource Allocation Agent. Your counter-proposal was rejected and the
proposer suggests a different alternative. Accept it if it is feasible and does not harm more urgent victims
elsewhere; otherwise deny it. Reply in one short sentence of reasoning."""

model = SETTINGS.llm.model
RA_AGENT = Agent(name="ResourceAllocationAgent", model=model, instructions=RA_INSTRUCTIONS, output_type=Resolution)
DISPATCH_NEGOTIATOR = Agent(name="DispatchNegotiator", model=model,
                            instructions=DISPATCH_NEGOTIATOR_INSTRUCTIONS, output_type=Reply)
HOSPITAL_NEGOTIATOR = Agent(name="HospitalNegotiator", model=model,
                            instructions=HOSPITAL_NEGOTIATOR_INSTRUCTIONS, output_type=Reply)
RA_FINAL_AGENT = Agent(name="ResourceAllocationFinal", model=model, instructions=RA_FINAL_INSTRUCTIONS,
                       output_type=FinalCall)


async def ask_resource_allocation(prompt: str) -> LLMResult:
    return await run_cached(RA_AGENT, prompt)


async def ask_proposer(proposer: AgentName, prompt: str) -> LLMResult:
    agent = DISPATCH_NEGOTIATOR if proposer == AgentName.DISPATCH else HOSPITAL_NEGOTIATOR
    return await run_cached(agent, prompt)


async def ask_final(prompt: str) -> LLMResult:
    return await run_cached(RA_FINAL_AGENT, prompt)


# ───────── Views for negotiation prompts (assessments only, never ground truth) ─────────
def describe(action: ProposedAction, incident_id: str, ctx: AgentContext) -> dict:
    s, inc = ctx.state, ctx.state.incidents[incident_id]
    if action.action_type == ActionType.ASSIGN_AMBULANCE:
        amb = s.ambulances[action.ambulance_id]
        return {"ambulance_id": amb.ambulance_id, "type": "ALS" if amb.ambulance_type == AmbulanceType.ALS else "BLS",
                "est_minutes_to_incident": estimated_minutes(amb.location, inc.location)}
    if action.action_type == ActionType.ASSIGN_RESPONDER:
        team = s.responders[action.responder_id]
        return {"team_id": team.team_id, "est_minutes_to_incident": estimated_minutes(team.location, inc.location)}
    h = s.hospitals[action.hospital_id]
    return {**_hospital_view(s, h), "est_minutes_from_incident": estimated_minutes(inc.location, h.location)}


def _victims_of(p: Proposal, ctx: AgentContext) -> list[dict]:
    ids = p.action.victim_ids or [v.victim_id for v in ctx.state.incidents[p.incident_id].victims
                                  if v.status == VictimStatus.WAITING]
    return [v for vid in ids if (v := _victim_view(ctx, vid))]


def proposal_view(p: Proposal, ctx: AgentContext) -> dict:
    s = ctx.state
    return {"proposal_id": p.proposal_id, "proposer": p.proposer.value, "incident_id": p.incident_id,
            "minutes_waiting": s.time_min - s.incidents[p.incident_id].arrival_time_min,
            "victims": _victims_of(p, ctx), "proposed": describe(p.action, p.incident_id, ctx),
            "proposer_reason": p.reason}


def unclaimed_alternatives(conflict: Conflict, ctx: AgentContext, taken: set[str]) -> dict:
    s, blocked = ctx.state, taken | set(conflict.resources)
    if conflict.conflict_type == ConflictType.RESOURCE:
        ambs = [a for a in s.available_ambulances() if f"ambulance:{a.ambulance_id}" not in blocked]
        return {"ambulances": [
            {"ambulance_id": a.ambulance_id, "type": "ALS" if a.ambulance_type == AmbulanceType.ALS else "BLS",
             "est_minutes_to": {i: estimated_minutes(a.location, s.incidents[i].location) for i in conflict.incident_ids}}
            for a in ambs]}
    return {"hospitals": [
        {**_hospital_view(s, h),
         "est_minutes_from": {i: estimated_minutes(s.incidents[i].location, h.location) for i in conflict.incident_ids}}
        for h in s.hospitals.values()]}


def _dump(header: str, payload: dict) -> str:
    return f"{header}\n{json.dumps(payload, separators=(',', ':'))}"


# ───────── The negotiating system ─────────
class NegotiatingSystem(AgentSystem):
    def __init__(self, oracle: bool = False) -> None:
        super().__init__(negotiate=True, oracle=oracle)

    async def _resolve(self, conflict: Conflict, ctx: AgentContext, chosen: set[str]) -> tuple[list[str], str]:
        t, nid = ctx.state.time_min, conflict.conflict_id
        header = f"Negotiation {nid} | minute {t} | state {state_fingerprint(ctx.state)}"
        by_id = {p.proposal_id: p for p in ctx.proposals}
        taken: set[str] = set()
        for pid in chosen - set(conflict.proposal_ids):
            taken |= claimed_keys(by_id[pid])
        alts = unclaimed_alternatives(conflict, ctx, taken)

        # Round 1: Resource Allocation decides
        res = await ask_resource_allocation(_dump(header, {
            "conflict": {"type": conflict.conflict_type.value, "reason": conflict.reason},
            "competing_proposals": [proposal_view(by_id[pid], ctx) for pid in conflict.proposal_ids],
            "unclaimed_alternatives": alts}))
        self._log_llm(t, RA, res)
        try:
            resolution = Resolution.model_validate(res.output)
        except ValidationError:
            return resolve_by_priority(conflict, ctx), "fallback"
        winners = [w for w in dict.fromkeys(resolution.winner_proposal_ids) if w in conflict.proposal_ids]
        if not winners or not self._compatible(winners, conflict, ctx, by_id):
            return resolve_by_priority(conflict, ctx), "fallback"
        for w in winners:
            taken |= claimed_keys(by_id[w])

        agreed = list(winners)
        for counter in resolution.counter_proposals:
            loser = by_id.get(counter.for_proposal_id)
            if loser is None or loser.proposal_id in winners or loser.proposal_id not in conflict.proposal_ids:
                continue
            offer = self._make_counter(loser, counter.alternative_id, ctx, taken, nid)
            if offer is None:
                self._record(t, "counter_invalid", negotiation_id=nid, for_proposal=loser.proposal_id,
                             alternative=counter.alternative_id)
                continue
            m1 = self._message(t, RA, loser.proposer, MessageType.COUNTER_PROPOSAL, loser.incident_id,
                               offer.action, loser.priority, counter.reason,
                               in_reply_to=self._proposal_msg.get(loser.proposal_id, loser.proposal_id),
                               negotiation_id=nid, round_=1)

            # Round 2: the losing proposer answers
            r2 = await ask_proposer(loser.proposer, _dump(header, {
                "your_proposal": proposal_view(loser, ctx),
                "rejected_because": conflict.reason,
                "counter_proposal": describe(offer.action, loser.incident_id, ctx),
                "unclaimed_alternatives": alts}))
            self._log_llm(t, loser.proposer, r2)
            try:
                reply = Reply.model_validate(r2.output)
            except ValidationError:
                reply = Reply(decision="reject", suggested_alternative_id="none", reason="unparseable reply")
            verdict = MessageType.ACCEPT if reply.decision == "accept" else MessageType.REJECT
            self._message(t, loser.proposer, RA, verdict, loser.incident_id, offer.action, loser.priority,
                          reply.reason, in_reply_to=m1, negotiation_id=nid, round_=2)
            if reply.decision == "accept":
                agreed.append(self._adopt(offer, ctx, taken))
                continue
            if reply.suggested_alternative_id.lower() == "none":
                continue
            suggestion = self._make_counter(loser, reply.suggested_alternative_id, ctx, taken, nid)
            if suggestion is None:
                continue
            m3 = self._message(t, loser.proposer, RA, MessageType.COUNTER_PROPOSAL, loser.incident_id,
                               suggestion.action, loser.priority, reply.reason, in_reply_to=m1,
                               negotiation_id=nid, round_=2)

            # Round 3: Resource Allocation accepts or denies the suggestion
            r3 = await ask_final(_dump(header, {
                "conflict_reason": conflict.reason,
                "proposer": loser.proposer.value, "incident_id": loser.incident_id,
                "victims": _victims_of(loser, ctx),
                "proposer_rejected_your_counter_because": reply.reason,
                "proposer_suggests": describe(suggestion.action, loser.incident_id, ctx)}))
            self._log_llm(t, RA, r3)
            try:
                final = FinalCall.model_validate(r3.output)
            except ValidationError:
                final = FinalCall(decision="deny", reason="unparseable final call")
            self._message(t, RA, loser.proposer,
                          MessageType.ACCEPT if final.decision == "accept" else MessageType.REJECT,
                          loser.incident_id, suggestion.action, loser.priority, final.reason,
                          in_reply_to=m3, negotiation_id=nid, round_=3)
            if final.decision == "accept":
                agreed.append(self._adopt(suggestion, ctx, taken))
        return agreed, "negotiation"

    # ───────── Helpers ─────────
    @staticmethod
    def _compatible(winners: list[str], conflict: Conflict, ctx: AgentContext, by_id: dict) -> bool:
        ps = [by_id[w] for w in winners]
        if conflict.conflict_type == ConflictType.CAPACITY:
            h = ctx.state.hospitals[ps[0].action.hospital_id]
            room = h.er_capacity - h.er_occupied - ctx.state.incoming_count(h.hospital_id)
            return sum(len(p.action.victim_ids) for p in ps) <= room
        if conflict.conflict_type == ConflictType.ROUTING:
            return len({p.action.hospital_id for p in ps}) == 1
        keys = [claimed_keys(p) for p in ps]
        return sum(len(k) for k in keys) == len(set().union(*keys))

    @staticmethod
    def _make_counter(loser: Proposal, alternative_id: str, ctx: AgentContext, taken: set[str],
                      nid: str) -> Proposal | None:
        a = loser.action
        try:
            if a.action_type == ActionType.ASSIGN_AMBULANCE:
                action = ProposedAction(action_type=a.action_type, ambulance_id=alternative_id, victim_ids=a.victim_ids)
            elif a.action_type in (ActionType.ADMIT_PATIENT, ActionType.DIVERT_PATIENT):
                action = ProposedAction(action_type=a.action_type, hospital_id=alternative_id, victim_ids=a.victim_ids)
            else:
                return None
        except ValidationError:
            return None
        if not validate(action, loser.incident_id, ctx.state).accepted:
            return None
        offer = Proposal(proposal_id=ctx.next_proposal_id(), proposer=loser.proposer, incident_id=loser.incident_id,
                         action=action, priority=loser.priority, reason=f"counter-proposal in {nid}",
                         time_min=ctx.state.time_min)
        return None if claimed_keys(offer) & taken else offer

    @staticmethod
    def _adopt(offer: Proposal, ctx: AgentContext, taken: set[str]) -> str:
        ctx.proposals.append(offer)
        taken |= claimed_keys(offer)
        return offer.proposal_id