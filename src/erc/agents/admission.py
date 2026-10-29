"""v2 hospital admission negotiation.

Dispatch requests a destination hospital for an ambulance's victims; Hospital Coordination reviews each
request (accept, reject, or counter with another hospital for the WHOLE load); Dispatch revises; after
3 rounds Resource Allocation arbitrates; the fixed rule (nearest capable hospital with room) is the last
resort. Everything is logged under the four project agents: dispatch, hospital_coordination,
resource_allocation (the classes below are implementation details).

Python owns reality: a ledger of beds promised during this review stops two accepts from overfilling an ER,
and every hospital that is accepted, countered or arbitrated passes the validator first. Without
negotiation (mode "agents") the review is the fixed rule: one pass, no counters, no rounds.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from agents import Agent
from pydantic import BaseModel, ValidationError

from erc.agents.context import AgentContext, Proposal, state_fingerprint
from erc.agents.llm_cache import LLMResult, run_cached
from erc.agents.tools import _victim_view, estimated_minutes, hospital_review_view
from erc.config import SETTINGS
from erc.models.messages import MAX_NEGOTIATION_ROUNDS, ActionType, AgentName, MessageType, ProposedAction
from erc.sim.validator import validate

D, H, RA = AgentName.DISPATCH, AgentName.HOSPITAL, AgentName.RESOURCE_ALLOCATION
NO_ID = "none"


# ───────── Structured outputs ─────────
class Review(BaseModel):
    request_id: str
    decision: Literal["accept", "reject", "counter"]
    counter_hospital_id: str        # another hospital for the whole load when countering, else 'none'
    reason: str


class Reviews(BaseModel):
    reviews: list[Review]


class Revision(BaseModel):
    request_id: str
    action: Literal["accept_counter", "request_other", "escalate"]
    hospital_id: str                # the hospital to request when action is request_other, else 'none'
    reason: str


class Revisions(BaseModel):
    revisions: list[Revision]


class Choice(BaseModel):
    request_id: str
    hospital_id: str                # 'none' if no option is acceptable
    reason: str


class Choices(BaseModel):
    choices: list[Choice]


# ───────── Agents (short prompts) ─────────
REVIEW_INSTRUCTIONS = """You are the Hospital Coordination Agent. Dispatch asks you to admit ambulance patients.
For each request answer accept, reject, or counter (name another hospital for the WHOLE load).
Protect capacity for critical (urgency 4-5) patients without stranding anyone: reject only to keep the last
bed(s) for assessed critical victims in waiting_critical who are closer to this hospital than to any other, and
only if another capable hospital has room. Otherwise accept. Give a one-sentence reason."""

REVISION_INSTRUCTIONS = """You are the Dispatch Agent. Hospital Coordination rejected or countered your admission
request. For each request choose accept_counter (if it still gets the patients timely care), request_other
(a hospital_id from options), or escalate. Give a one-sentence reason."""

ARBITER_INSTRUCTIONS = """You are the Resource Allocation Agent. Dispatch and Hospital Coordination could not agree
on a hospital. For each request pick the option that reaches the most urgent patients in time without overloading
an ER, or 'none'. Give a one-sentence reason."""

model = SETTINGS.llm.model
REVIEW_AGENT = Agent(name="HospitalReviewer", model=model, instructions=REVIEW_INSTRUCTIONS, output_type=Reviews)
REVISION_AGENT = Agent(name="DispatchRevisionAgent", model=model, instructions=REVISION_INSTRUCTIONS,
                       output_type=Revisions)
ARBITER_AGENT = Agent(name="AdmissionArbiter", model=model, instructions=ARBITER_INSTRUCTIONS, output_type=Choices)


async def ask_review(prompt: str) -> LLMResult:
    return await run_cached(REVIEW_AGENT, prompt)


async def ask_revision(prompt: str) -> LLMResult:
    return await run_cached(REVISION_AGENT, prompt)


async def ask_arbiter(prompt: str) -> LLMResult:
    return await run_cached(ARBITER_AGENT, prompt)


# ───────── One request being negotiated ─────────
@dataclass
class Case:
    req: Proposal
    nid: str
    hospital_id: str                 # hospital currently requested
    request_mid: str
    round: int = 1
    outcome: str | None = None       # hospital finally chosen
    method: str = "pending"
    last: str = ""                   # hospital's last answer: reject | counter
    counter: str | None = None
    counter_mid: str | None = None
    escalate_mid: str | None = None
    escalated: bool = False
    history: list[dict] = field(default_factory=list)

    @property
    def rid(self) -> str:
        return self.req.proposal_id

    @property
    def victims(self) -> list[str]:
        return self.req.action.victim_ids


def _dump(header: str, payload: dict) -> str:
    return f"{header}\n{json.dumps(payload, separators=(',', ':'))}"


class AdmissionProtocol:
    def __init__(self, system, negotiate: bool) -> None:
        self.sys, self.negotiate = system, negotiate
        self.held: dict[str, int] = {}      # beds promised during this review, per hospital

    # ───────── Entry point ─────────
    async def run(self, ctx: AgentContext, requests: list[Proposal]) -> list[Proposal]:
        """Returns one admission proposal per resolved request (same proposal ID as the request)."""
        self.ctx, self.t = ctx, ctx.state.time_min
        self.header = f"Admissions {ctx.round_id} | minute {self.t} | state {state_fingerprint(ctx.state)}"
        cases = [self._open(i, p) for i, p in enumerate(requests, 1)]
        for rnd in range(1, (MAX_NEGOTIATION_ROUNDS if self.negotiate else 1) + 1):
            active = [c for c in cases if c.outcome is None and not c.escalated]
            if not active:
                break
            await self._review(active, rnd)
            if self.negotiate:
                await self._revise([c for c in active if c.outcome is None], rnd)
        if self.negotiate:
            await self._arbitrate([c for c in cases if c.outcome is None])
            self._fallback([c for c in cases if c.outcome is None])
        for c in cases:
            self.sys._record(self.t, "admission_resolved", negotiation_id=c.nid, incident_id=c.req.incident_id,
                             victim_ids=c.victims, requested=c.req.action.hospital_id, hospital_id=c.outcome,
                             method=c.method, rounds=c.round)
            if c.outcome:
                self.sys._proposal_msg[c.rid] = c.request_mid
        return [self._final(c) for c in cases if c.outcome]

    # ───────── Messages ─────────
    def _action(self, c: Case, hospital_id: str) -> ProposedAction:
        return ProposedAction(action_type=ActionType.ADMIT_PATIENT, hospital_id=hospital_id, victim_ids=c.victims)

    def _msg(self, c: Case, sender: AgentName, recipient: AgentName, mtype: MessageType, hospital_id: str | None,
             reason: str, rnd: int, reply_to: str | None = None) -> str:
        action = self._action(c, hospital_id) if hospital_id else None
        return self.sys._message(self.t, sender, recipient, mtype, c.req.incident_id, action, c.req.priority,
                                 reason, in_reply_to=reply_to, negotiation_id=c.nid, round_=rnd)

    def _open(self, n: int, req: Proposal) -> Case:
        nid = f"ADM-{self.ctx.round_id}-{n:02d}"
        c = Case(req=req, nid=nid, hospital_id=req.action.hospital_id, request_mid="")
        c.request_mid = self._msg(c, D, H, MessageType.PROPOSAL, c.hospital_id, req.reason, 1)
        return c

    def _final(self, c: Case) -> Proposal:
        return c.req.model_copy(update={"action": self._action(c, c.outcome),
                                        "reason": f"admission {c.nid}: {c.method}"})

    # ───────── Feasibility (validator + ledger) ─────────
    def _room(self, hospital_id: str) -> int:
        s, h = self.ctx.state, self.ctx.state.hospitals[hospital_id]
        return h.er_capacity - h.er_occupied - s.incoming_count(hospital_id) - self.held.get(hospital_id, 0)

    def _feasible(self, c: Case, hospital_id: str) -> bool:
        if hospital_id not in self.ctx.state.hospitals:
            return False
        if not validate(self._action(c, hospital_id), c.req.incident_id, self.ctx.state).accepted:
            return False
        return self._room(hospital_id) >= len(c.victims)

    def _options(self, c: Case) -> list[dict]:
        s, loc = self.ctx.state, self.ctx.state.incidents[c.req.incident_id].location
        return [{"hospital_id": h.hospital_id, "est_minutes": estimated_minutes(loc, h.location),
                 "room": self._room(h.hospital_id)}
                for h in s.hospitals.values() if self._feasible(c, h.hospital_id)]

    def _nearest(self, c: Case) -> str | None:
        options = self._options(c)
        return min(options, key=lambda o: (o["est_minutes"], o["hospital_id"]))["hospital_id"] if options else None

    def _take(self, c: Case, hospital_id: str, method: str) -> None:
        self.held[hospital_id] = self.held.get(hospital_id, 0) + len(c.victims)
        c.outcome, c.method = hospital_id, method

    def _note(self, c: Case, who: str, decision: str, reason: str, hospital_id: str | None = None) -> None:
        c.history.append({"round": c.round, "by": who, "decision": decision, "hospital_id": hospital_id,
                          "reason": reason})

    def _llm_failed(self, stage: str, detail: str) -> None:
        self.sys._record(self.t, "admission_fallback", stage=stage, detail=detail)

    # ───────── Hospital review ─────────
    def _rule_review(self, c: Case) -> tuple[Review, str | None]:
        """Fixed rule: accept if capable and room, else the nearest capable hospital with room."""
        if self._feasible(c, c.hospital_id):
            return Review(request_id=c.rid, decision="accept", counter_hospital_id=NO_ID,
                          reason="rule: capable and has room"), None
        alt = self._nearest(c)
        return Review(request_id=c.rid, decision="reject", counter_hospital_id=NO_ID,
                      reason=f"rule: {c.hospital_id} is incapable or full"), alt

    async def _llm_reviews(self, cases: list[Case], rnd: int) -> dict[str, Review]:
        s = self.ctx.state
        requests = [{"request_id": c.rid, "ambulance_id": s.reservations.get(c.victims[0]),
                     "victims": [v for vid in c.victims if (v := _victim_view(self.ctx, vid))],
                     "requested_hospital": c.hospital_id, "dispatch_reason": c.req.reason,
                     "est_minutes_to": {o["hospital_id"]: o["est_minutes"] for o in self._options(c)}}
                    for c in cases]
        view = hospital_review_view(self.ctx, requests, self.held)
        res = await ask_review(_dump(self.header, {"round": rnd, **view}))
        self.sys._log_llm(self.t, H, res)
        try:
            return {r.request_id: r for r in Reviews.model_validate(res.output).reviews}
        except ValidationError:
            self._llm_failed("review", "unparseable hospital review")
            return {}

    async def _review(self, cases: list[Case], rnd: int) -> None:
        reviews = await self._llm_reviews(cases, rnd) if self.negotiate else {}
        for c in cases:
            redirect, review = None, reviews.get(c.rid)
            if review is None:
                review, alt = self._rule_review(c)
                redirect = alt if not self.negotiate else None
            self._apply_review(c, review, rnd, redirect)

    def _apply_review(self, c: Case, r: Review, rnd: int, redirect: str | None) -> None:
        hosp = c.hospital_id
        if r.decision == "accept":
            if self._feasible(c, hosp):
                self._msg(c, H, D, MessageType.ACCEPT, hosp, r.reason, rnd, c.request_mid)
                self._take(c, hosp, "accepted" if rnd == 1 else "revised")
                return
            r = Review(request_id=c.rid, decision="reject", counter_hospital_id=NO_ID,
                       reason=f"{hosp} has no room left")
        if r.decision == "counter":
            if r.counter_hospital_id != hosp and self._feasible(c, r.counter_hospital_id):
                c.counter = r.counter_hospital_id
                c.counter_mid = self._msg(c, H, D, MessageType.COUNTER_PROPOSAL, c.counter, r.reason, rnd,
                                          c.request_mid)
                c.last = "counter"
                self._note(c, "hospital", "counter", r.reason, c.counter)
                return
            r = Review(request_id=c.rid, decision="reject", counter_hospital_id=NO_ID,
                       reason=f"counter {r.counter_hospital_id} is not feasible")
        self._msg(c, H, D, MessageType.REJECT, hosp, r.reason, rnd, c.request_mid)
        c.counter, c.last = None, "reject"
        self._note(c, "hospital", "reject", r.reason)
        if redirect:
            self.sys._record(self.t, "admission_redirect", negotiation_id=c.nid, victim_ids=c.victims,
                             from_hospital=hosp, hospital_id=redirect, reason=r.reason)
            self._take(c, redirect, "redirect")

    # ───────── Dispatch revision ─────────
    async def _revise(self, cases: list[Case], rnd: int) -> None:
        if not cases:
            return
        payload = {"round": rnd, "requests": [
            {"request_id": c.rid, "victims": [v for vid in c.victims if (v := _victim_view(self.ctx, vid))],
             "requested": c.hospital_id, "hospital_said": c.last, "reason": c.history[-1]["reason"],
             "counter_offer": c.counter, "options": self._options(c)} for c in cases]}
        res = await ask_revision(_dump(self.header, payload))
        self.sys._log_llm(self.t, D, res)
        try:
            revisions = {r.request_id: r for r in Revisions.model_validate(res.output).revisions}
        except ValidationError:
            self._llm_failed("revision", "unparseable dispatch revision")
            revisions = {}
        for c in cases:
            rev = revisions.get(c.rid)
            if rev and rev.action == "accept_counter" and c.counter and self._feasible(c, c.counter):
                self._msg(c, D, H, MessageType.ACCEPT, c.counter, rev.reason, rnd, c.counter_mid)
                self._take(c, c.counter, "counter_accepted")
            elif (rev and rev.action == "request_other" and rnd < MAX_NEGOTIATION_ROUNDS
                  and rev.hospital_id != c.hospital_id and self._feasible(c, rev.hospital_id)):
                c.round, c.hospital_id, c.counter = rnd + 1, rev.hospital_id, None
                c.request_mid = self._msg(c, D, H, MessageType.PROPOSAL, c.hospital_id, rev.reason, c.round)
                self._note(c, "dispatch", "request_other", rev.reason, c.hospital_id)
            else:
                c.escalated = True

    # ───────── Resource Allocation arbitration, then fixed rule ─────────
    async def _arbitrate(self, cases: list[Case]) -> None:
        if not cases:
            return
        for c in cases:
            why = c.history[-1]["reason"] if c.history else "no agreement"
            c.escalate_mid = self._msg(c, D, RA, MessageType.ESCALATE, None, why, c.round)
        payload = {"requests": [
            {"request_id": c.rid, "victims": [v for vid in c.victims if (v := _victim_view(self.ctx, vid))],
             "history": c.history, "options": self._options(c)} for c in cases]}
        res = await ask_arbiter(_dump(self.header, payload))
        self.sys._log_llm(self.t, RA, res)
        try:
            choices = {r.request_id: r for r in Choices.model_validate(res.output).choices}
        except ValidationError:
            self._llm_failed("arbitration", "unparseable arbitration")
            choices = {}
        for c in cases:
            ch = choices.get(c.rid)
            if ch and ch.hospital_id != NO_ID and self._feasible(c, ch.hospital_id):
                self._msg(c, RA, D, MessageType.ACCEPT, ch.hospital_id, ch.reason, c.round, c.escalate_mid)
                self._take(c, ch.hospital_id, "arbitrated")

    def _fallback(self, cases: list[Case]) -> None:
        for c in cases:
            alt = self._nearest(c)
            if alt is None:
                continue                      # no capable hospital has room: stays pending, like a v1 HOSPITAL_FULL
            self.sys._record(self.t, "admission_fallback", stage="rule", negotiation_id=c.nid,
                             victim_ids=c.victims, hospital_id=alt)
            self._msg(c, RA, D, MessageType.ACCEPT, alt, "fallback rule: nearest capable hospital with room",
                      c.round, c.escalate_mid or c.request_mid)
            self._take(c, alt, "fallback")
