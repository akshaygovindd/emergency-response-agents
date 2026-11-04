"""v3 staff-sharing negotiation between hospitals.

One Hospital Coordination instance runs per hospital (hospital_coordination:H-T, :H-B, :H-G): the same agent
definition and instructions for all three, each given only its OWN hospital's state and interests. A borrower
instance asks a lender instance for a doctor + nurse team and one treatment slot of a care type; the lender
accepts, rejects (for example to protect capacity for its own incoming critical patients) or counters with fewer
teams or a shorter loan; the borrower revises; after 3 rounds Resource Allocation arbitrates; the fixed rule is
the last resort. Without negotiation (mode "agents") the lender decision is the fixed rule: one pass, no counters.

Python owns reality: the trigger, the candidate lenders and every hard rule come from sim/loans.py, a ledger
stops one slot or person being lent twice in a round, and the engine validates again at execution.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from agents import Agent
from pydantic import BaseModel, ValidationError

from erc.agents.context import AgentContext, state_fingerprint
from erc.agents.llm_cache import LLMResult, run_cached
from erc.agents.tools import _victim_view, estimated_minutes
from erc.config import SETTINGS
from erc.models.entities import Capability, StaffRole
from erc.models.messages import MAX_NEGOTIATION_ROUNDS, ActionType, AgentName, LoanSpec, MessageType, ProposedAction
from erc.sim import loans as L

H, RA = AgentName.HOSPITAL, AgentName.RESOURCE_ALLOCATION
NO_ID = "none"
CFG = SETTINGS.loans


# ───────── Structured outputs ─────────
class Ask(BaseModel):
    care: Literal["trauma", "burn", "general"]
    lender_id: str
    teams: int
    duration_min: int
    reason: str


class Asks(BaseModel):
    asks: list[Ask]


class Answer(BaseModel):
    request_id: str
    decision: Literal["accept", "reject", "counter"]
    teams: int                      # for a counter: the teams you offer, else the teams requested
    duration_min: int               # for a counter: the duration you offer, else the duration requested
    reason: str


class Answers(BaseModel):
    answers: list[Answer]


class Revision(BaseModel):
    request_id: str
    action: Literal["accept_counter", "request_other", "escalate"]
    lender_id: str                  # lender to ask when action is request_other, else 'none'
    teams: int
    duration_min: int
    reason: str


class Revisions(BaseModel):
    revisions: list[Revision]


class Allocation(BaseModel):
    request_id: str
    lender_id: str                  # 'none' if no option is acceptable
    teams: int
    duration_min: int
    reason: str


class Allocations(BaseModel):
    allocations: list[Allocation]


# ───────── Agents (short prompts) ─────────
HOSPITAL_LOAN_INSTRUCTIONS = f"""You are the Hospital Coordination Agent of ONE hospital. You see only your own hospital's
state (own) and act in its interest while helping patients system-wide. A loan moves one treatment slot of a care type
and one doctor + nurse team (per team) from a lender to a borrower for duration_min, plus travel time each way; the
lender is short that slot and team until they return. teams is 1..{CFG.max_teams}; duration_min is {CFG.min_duration_min}..{CFG.max_duration_min}.
Your role is given in the input.
- borrower: for each need, ask ONE lender from its candidates (teams no larger than uncovered). Prefer a near lender and a
  loan long enough to cover the queue (queued patients and their urgency are in own).
- lender: answer every request with accept, reject, or counter (fewer teams and/or a shorter duration). Reject to keep
  capacity for your own queued or en-route patients, above all critical (urgency 4-5) ones; otherwise accept.
- revise: your request was rejected or countered. For each request accept_counter, request_other (a hospital_id from
  options, with teams and duration), or escalate. Give a one-sentence reason."""

LOAN_ARBITER_INSTRUCTIONS = """You are the Resource Allocation Agent. Hospitals could not agree on a staff loan, or several
requests compete for the same lender. For each request pick the lender, teams and duration (from options) that serve the
most urgent queued patients without leaving a lender short for its own patients, or lender_id 'none'. One sentence of reason."""

model = SETTINGS.llm.model
LOAN_AGENT = Agent(name="HospitalLoanAgent", model=model, instructions=HOSPITAL_LOAN_INSTRUCTIONS)
ASK_AGENT = LOAN_AGENT.clone(output_type=Asks)
ANSWER_AGENT = LOAN_AGENT.clone(output_type=Answers)
REVISE_AGENT = LOAN_AGENT.clone(output_type=Revisions)
ARBITER_AGENT = Agent(name="LoanArbiter", model=model, instructions=LOAN_ARBITER_INSTRUCTIONS, output_type=Allocations)


async def ask_asks(prompt: str) -> LLMResult:
    return await run_cached(ASK_AGENT, prompt)


async def ask_answers(prompt: str) -> LLMResult:
    return await run_cached(ANSWER_AGENT, prompt)


async def ask_revisions(prompt: str) -> LLMResult:
    return await run_cached(REVISE_AGENT, prompt)


async def ask_allocation(prompt: str) -> LLMResult:
    return await run_cached(ARBITER_AGENT, prompt)


def _dump(header: str, payload: dict) -> str:
    return f"{header}\n{json.dumps(payload, separators=(',', ':'))}"


# ───────── One request being negotiated ─────────
@dataclass
class Case:
    nid: str
    borrower: str
    cap: Capability
    serves: list[str]
    incident_id: str
    priority: int
    urgency: int                     # highest assessed urgency among the patients served
    uncovered: int
    lender: str
    teams: int
    duration: int
    reason: str
    request_mid: str = ""
    round: int = 1
    outcome: LoanSpec | None = None
    method: str = "pending"
    last: str = ""                   # lender's last answer: reject | counter
    counter: tuple[int, int] | None = None      # (teams, duration) offered
    counter_mid: str | None = None
    escalate_mid: str | None = None
    escalated: bool = False
    history: list[dict] = field(default_factory=list)

    @property
    def rid(self) -> str:
        return self.nid

    def spec(self, lender: str | None = None, teams: int | None = None, duration: int | None = None) -> LoanSpec:
        return LoanSpec(lender_id=lender or self.lender, borrower_id=self.borrower, capability=self.cap,
                        teams=teams or self.teams, duration_min=duration or self.duration, serves=self.serves)


@dataclass
class Committed:
    spec: LoanSpec
    incident_id: str
    priority: int
    request_mid: str
    method: str


class LoanProtocol:
    def __init__(self, system, negotiate: bool) -> None:
        self.sys, self.negotiate = system, negotiate
        self.ledger = L.Ledger()

    # ───────── Entry point ─────────
    async def run(self, ctx: AgentContext, needs: list[L.LoanNeed]) -> list[Committed]:
        self.ctx, self.t, self.state = ctx, ctx.state.time_min, ctx.state
        self.header = f"Loans {ctx.round_id} | minute {self.t} | state {state_fingerprint(ctx.state)}"
        cases = await self._open(needs)
        for rnd in range(1, (MAX_NEGOTIATION_ROUNDS if self.negotiate else 1) + 1):
            active = [c for c in cases if c.outcome is None and not c.escalated]
            if not active:
                break
            await self._contend(active)
            await self._review([c for c in active if c.outcome is None and not c.escalated], rnd)
            if self.negotiate:
                await self._revise([c for c in active if c.outcome is None and not c.escalated], rnd)
            else:
                self._redirect([c for c in active if c.outcome is None])
        if self.negotiate:
            await self._arbitrate([c for c in cases if c.outcome is None])
            self._fallback([c for c in cases if c.outcome is None])
        out = []
        for c in cases:
            self.sys._record(self.t, "loan_resolved", negotiation_id=c.nid, borrower_id=c.borrower,
                             capability=c.cap.value, requested=c.lender, lender_id=c.outcome.lender_id if c.outcome else None,
                             teams=c.outcome.teams if c.outcome else 0,
                             duration_min=c.outcome.duration_min if c.outcome else 0, method=c.method, rounds=c.round)
            if c.outcome:
                out.append(Committed(c.outcome, c.incident_id, c.priority, c.request_mid, c.method))
        return out

    # ───────── Views: each instance sees only its own hospital ─────────
    def _assessed(self, victims) -> list[dict]:
        return [v for x in victims if (v := _victim_view(self.ctx, x.victim_id))]

    def _own_view(self, hid: str) -> dict:
        s, h = self.state, self.state.hospitals[hid]
        queued = [v for v in s.victims() if s.admissions.get(v.victim_id) == hid and v.status.value == "awaiting_treatment"]
        away = L.on_loan_ids(s)
        idle = {}
        for cap in h.treatment_slots:
            docs = L.idle_staff(s, hid, StaffRole.DOCTOR, cap, away | self.ledger.staff)
            nurses = L.idle_staff(s, hid, StaffRole.NURSE, cap, away | self.ledger.staff)
            idle[cap.value] = min(len(docs), len(nurses))
        return {"hospital_id": hid, "name": h.name,
                "care": {c.value: {"slots": n, "free": h.free_slots(c) - self.ledger.slots_out.get((hid, c), 0)}
                         for c, n in h.treatment_slots.items()},
                "idle_teams": idle,
                "queued": self._assessed(queued), "en_route": self._assessed(L.incoming(s, hid)),
                "loans": [{"loan_id": ln.loan_id, "care": ln.capability.value, "teams": ln.teams,
                           "role": "borrower" if ln.borrower_id == hid else "lender", "phase": ln.phase.value}
                          for ln in s.loans_in_flight() if hid in (ln.borrower_id, ln.lender_id)]}

    def _minutes(self, a: str, b: str) -> int:
        return estimated_minutes(self.state.hospitals[a].location, self.state.hospitals[b].location)

    # ───────── Messages ─────────
    def _msg(self, c: Case, sender: AgentName, s_inst: str | None, recipient: AgentName, r_inst: str | None,
             mtype: MessageType, spec: LoanSpec | None, reason: str, rnd: int, reply_to: str | None = None) -> str:
        action = ProposedAction(action_type=ActionType.LOAN_STAFF, loan=spec) if spec else None
        return self.sys._message(self.t, sender, recipient, mtype, c.incident_id, action, c.priority, reason,
                                 in_reply_to=reply_to, negotiation_id=c.nid, round_=rnd,
                                 sender_instance=s_inst, recipient_instance=r_inst)

    def _h2h(self, c: Case, frm: str, to: str, mtype: MessageType, spec: LoanSpec | None, reason: str, rnd: int,
             reply_to: str | None = None) -> str:
        return self._msg(c, H, frm, H, to, mtype, spec, reason, rnd, reply_to)

    # ───────── Feasibility ─────────
    def _feasible(self, spec: LoanSpec) -> bool:
        return L.check_loan(self.state, spec, self.ledger).accepted

    def _critical_at(self, hid: str) -> bool:
        """Assessed-critical patient queued or en route at this hospital (what the fixed rule protects)."""
        s = self.state
        queued = [v for v in s.victims() if s.admissions.get(v.victim_id) == hid and v.status.value == "awaiting_treatment"]
        return any(v["urgency"] >= 4 for v in self._assessed([*queued, *L.incoming(s, hid)]))

    def _rule_accepts(self, spec: LoanSpec) -> bool:
        return self._feasible(spec) and not self._critical_at(spec.lender_id)

    def _take(self, c: Case, spec: LoanSpec, method: str) -> None:
        picked = L.pick_staff(self.state, spec, self.ledger)
        self.ledger.reserve(spec, *picked)
        c.outcome, c.method = spec, method

    def _note(self, c: Case, who: str, decision: str, reason: str, lender: str | None = None) -> None:
        c.history.append({"round": c.round, "by": who, "decision": decision, "lender_id": lender, "reason": reason})

    def _llm_failed(self, stage: str, detail: str) -> None:
        self.sys._record(self.t, "loan_fallback", stage=stage, detail=detail)

    def _options(self, c: Case) -> list[dict]:
        out = []
        for hid in self.state.hospitals:
            if hid != c.borrower:
                spec = c.spec(hid, 1, CFG.min_duration_min)
                if self._feasible(spec):
                    out.append({"hospital_id": hid, "est_minutes": self._minutes(hid, c.borrower)})
        return sorted(out, key=lambda o: (o["est_minutes"], o["hospital_id"]))

    # ───────── Step 1: borrower instances ask ─────────
    def _new_case(self, n: int, need: L.LoanNeed, ask: Ask | None) -> Case | None:
        views = self._assessed([self.state.find_victim(v) for v in need.victim_ids])
        urgency = max((v["urgency"] for v in views), default=3)
        first = self.state.find_victim(need.victim_ids[0])
        lender, teams, duration, reason = ((ask.lender_id, ask.teams, ask.duration_min, ask.reason) if ask else
                                           (need.lenders[0], 1, CFG.default_duration_min, "rule: nearest feasible lender"))
        duration = min(CFG.max_duration_min, max(CFG.min_duration_min, duration))
        c = Case(nid=f"LN-{self.ctx.round_id}-{n:02d}", borrower=need.borrower_id, cap=need.capability,
                 serves=need.victim_ids, incident_id=first.incident_id, priority=max(1, min(5, 6 - urgency)),
                 urgency=urgency, uncovered=need.uncovered, lender=lender, teams=teams, duration=duration, reason=reason)
        return c

    async def _open(self, needs: list[L.LoanNeed]) -> list[Case]:
        by_borrower: dict[str, list[L.LoanNeed]] = {}
        for n in needs:
            by_borrower.setdefault(n.borrower_id, []).append(n)
        cases: list[Case] = []
        for bid, group in sorted(by_borrower.items()):
            for n in group:
                self.sys._record(self.t, "loan_trigger", borrower_id=bid, capability=n.capability.value,
                                 uncovered=n.uncovered, queued=n.victim_ids, lenders=n.lenders)
            asks = await self._asks(bid, group)
            for need in group:
                ask = next((a for a in asks if a.care == need.capability.value), None)
                c = None
                if ask is not None:
                    cand = self._new_case(len(cases) + 1, need, ask)
                    spec = cand.spec()
                    if (ask.lender_id in need.lenders and ask.teams <= need.uncovered and self._feasible(spec)):
                        c = cand
                    else:
                        self.sys._record(self.t, "proposal_invalid", agent=f"hospital_coordination:{bid}",
                                         detail=f"infeasible loan ask {ask.lender_id} x{ask.teams} for {need.capability.value}")
                if c is None:
                    if self.negotiate or ask is None:
                        self.sys._record(self.t, "loan_fallback", stage="request", borrower_id=bid,
                                         capability=need.capability.value)
                    c = self._new_case(len(cases) + 1, need, None)
                c.request_mid = self._h2h(c, bid, c.lender, MessageType.REQUEST, c.spec(), c.reason, 1)
                cases.append(c)
        return cases

    async def _asks(self, bid: str, group: list[L.LoanNeed]) -> list[Ask]:
        payload = {"role": "borrower", "own": self._own_view(bid), "needs": [
            {"care": n.capability.value, "uncovered": n.uncovered,
             "lenders": [{"hospital_id": l, "est_minutes": self._minutes(l, bid)} for l in n.lenders]} for n in group]}
        res = await ask_asks(_dump(self.header, payload))
        self.sys._log_llm(self.t, H, res, instance=bid)
        try:
            return Asks.model_validate(res.output).asks
        except ValidationError:
            self._llm_failed("ask", f"unparseable loan ask from {bid}")
            return []

    # ───────── Step 2: contention for the same lender and care type ─────────
    def _priority_key(self, c: Case):
        return (-c.urgency, c.borrower, c.nid)

    async def _contend(self, cases: list[Case]) -> None:
        groups: dict[tuple[str, Capability], list[Case]] = {}
        for c in cases:
            groups.setdefault((c.lender, c.cap), []).append(c)
        for (lender, cap), group in groups.items():
            if len(group) < 2:
                continue
            probe, fits = L.Ledger(), True
            for c in group:                                  # can the lender serve everybody at once?
                if not L.check_loan(self.state, c.spec(), probe).accepted:
                    fits = False
                    break
                probe.reserve(c.spec(), *L.pick_staff(self.state, c.spec(), probe))
            if fits:
                continue                                    # enough for everybody: no contention
            order = sorted(group, key=self._priority_key)
            method = "priority_rule"
            if self.negotiate:
                order, method = await self._ra_order(group, order)
            for c in group:
                c.escalate_mid = self._msg(c, H, c.borrower, RA, None, MessageType.ESCALATE, c.spec(),
                                           f"competing requests for {lender} {cap.value}", c.round, c.request_mid)
            probe, winners = L.Ledger(), set()
            for c in order:
                if L.check_loan(self.state, c.spec(), probe).accepted:
                    probe.reserve(c.spec(), *L.pick_staff(self.state, c.spec(), probe))
                    winners.add(c.nid)
            for c in group:
                won = c.nid in winners
                self._msg(c, RA, None, H, c.borrower, MessageType.ACCEPT if won else MessageType.REJECT,
                          c.spec() if won else None, f"{method}: {'first claim on' if won else 'lost'} {lender} {cap.value}",
                          c.round, c.escalate_mid)
                if not won:
                    c.last = "reject"
                    self._note(c, "resource_allocation", "reject", f"lender {lender} {cap.value} went to a more urgent request")
            self.sys._record(self.t, "loan_contention", lender_id=lender, capability=cap.value, method=method,
                             winners=sorted(winners), losers=sorted(c.nid for c in group if c.nid not in winners))

    async def _ra_order(self, group: list[Case], fallback: list[Case]) -> tuple[list[Case], str]:
        payload = {"requests": [{"request_id": c.nid, "borrower_id": c.borrower, "teams": c.teams, "duration_min": c.duration,
                                 "urgency": c.urgency, "queued": len(c.serves), "options": self._options(c)} for c in group]}
        res = await ask_allocation(_dump(self.header + " | contention", payload))
        self.sys._log_llm(self.t, RA, res)
        try:
            ids = [a.request_id for a in Allocations.model_validate(res.output).allocations if a.lender_id != NO_ID]
        except ValidationError:
            self._llm_failed("contention", "unparseable contention arbitration")
            return fallback, "fallback"
        first = [c for i in dict.fromkeys(ids) for c in group if c.nid == i]
        return first + [c for c in fallback if c not in first], "negotiation"

    # ───────── Step 3: lender instances answer ─────────
    def _rule_answer(self, c: Case) -> Answer:
        if self._rule_accepts(c.spec()):
            return Answer(request_id=c.nid, decision="accept", teams=c.teams, duration_min=c.duration,
                          reason="rule: idle slot and team, no critical patient of its own")
        why = "critical patient of its own" if self._critical_at(c.lender) else "no idle slot or team to spare"
        return Answer(request_id=c.nid, decision="reject", teams=c.teams, duration_min=c.duration, reason=f"rule: {why}")

    async def _llm_answers(self, lender: str, cases: list[Case], rnd: int) -> dict[str, Answer]:
        payload = {"role": "lender", "round": rnd, "own": self._own_view(lender), "requests": [
            {"request_id": c.nid, "borrower_id": c.borrower, "care": c.cap.value, "teams": c.teams,
             "duration_min": c.duration, "serves_urgencies": sorted(
                 (v["urgency"] for v in self._assessed([self.state.find_victim(x) for x in c.serves])), reverse=True),
             "est_minutes": self._minutes(lender, c.borrower), "reason": c.reason} for c in cases]}
        res = await ask_answers(_dump(self.header, payload))
        self.sys._log_llm(self.t, H, res, instance=lender)
        try:
            return {a.request_id: a for a in Answers.model_validate(res.output).answers}
        except ValidationError:
            self._llm_failed("review", f"unparseable lender answer from {lender}")
            return {}

    async def _review(self, cases: list[Case], rnd: int) -> None:
        by_lender: dict[str, list[Case]] = {}
        for c in cases:
            by_lender.setdefault(c.lender, []).append(c)
        for lender, group in sorted(by_lender.items()):
            group.sort(key=self._priority_key)
            answers = await self._llm_answers(lender, group, rnd) if self.negotiate else {}
            for c in group:
                ans = answers.get(c.nid) or self._rule_answer(c)
                self._apply_answer(c, lender, ans, rnd)

    def _apply_answer(self, c: Case, lender: str, a: Answer, rnd: int) -> None:
        asked = c.spec()
        if a.decision == "accept":
            if self._feasible(asked):
                self._h2h(c, lender, c.borrower, MessageType.ACCEPT, asked, a.reason, rnd, c.request_mid)
                self._take(c, asked, "accepted" if rnd == 1 else "revised")
                return
            a = Answer(request_id=c.nid, decision="reject", teams=c.teams, duration_min=c.duration,
                       reason=f"{lender} can no longer spare it")
        if a.decision == "counter":
            teams = min(c.teams, max(1, a.teams))
            dur = min(c.duration, max(CFG.min_duration_min, a.duration_min))
            offer = c.spec(teams=teams, duration=dur)
            if (teams, dur) != (c.teams, c.duration) and self._feasible(offer):
                c.counter = (teams, dur)
                c.counter_mid = self._h2h(c, lender, c.borrower, MessageType.COUNTER_PROPOSAL, offer, a.reason, rnd, c.request_mid)
                c.last = "counter"
                self._note(c, f"hospital_coordination:{lender}", "counter", a.reason, lender)
                return
            a = Answer(request_id=c.nid, decision="reject", teams=c.teams, duration_min=c.duration,
                       reason="counter was not feasible")
        self._h2h(c, lender, c.borrower, MessageType.REJECT, None, a.reason, rnd, c.request_mid)
        c.counter, c.last = None, "reject"
        self._note(c, f"hospital_coordination:{lender}", "reject", a.reason)

    # ───────── agents mode: the fixed rule tries the next nearest lender ─────────
    def _redirect(self, cases: list[Case]) -> None:
        for c in cases:
            for opt in self._options(c):
                alt = opt["hospital_id"]
                if alt == c.lender:
                    continue
                spec = c.spec(alt)
                if self._rule_accepts(spec):
                    self.sys._record(self.t, "loan_redirect", negotiation_id=c.nid, borrower_id=c.borrower,
                                     from_lender=c.lender, lender_id=alt)
                    c.lender = alt
                    c.request_mid = self._h2h(c, c.borrower, alt, MessageType.REQUEST, spec, "rule: next nearest lender", 1)
                    self._h2h(c, alt, c.borrower, MessageType.ACCEPT, spec, "rule: idle slot and team, no critical patient of its own",
                              1, c.request_mid)
                    self._take(c, spec, "redirect")
                    break

    # ───────── Step 4: borrower revises (negotiation only) ─────────
    async def _revise(self, cases: list[Case], rnd: int) -> None:
        by_borrower: dict[str, list[Case]] = {}
        for c in cases:
            by_borrower.setdefault(c.borrower, []).append(c)
        for bid, group in sorted(by_borrower.items()):
            payload = {"role": "revise", "round": rnd, "own": self._own_view(bid), "requests": [
                {"request_id": c.nid, "care": c.cap.value, "asked": c.lender, "teams": c.teams, "duration_min": c.duration,
                 "lender_said": c.last, "reason": c.history[-1]["reason"] if c.history else "-",
                 "counter": {"teams": c.counter[0], "duration_min": c.counter[1]} if c.counter else None,
                 "options": self._options(c)} for c in group]}
            res = await ask_revisions(_dump(self.header, payload))
            self.sys._log_llm(self.t, H, res, instance=bid)
            try:
                revs = {r.request_id: r for r in Revisions.model_validate(res.output).revisions}
            except ValidationError:
                self._llm_failed("revision", f"unparseable revision from {bid}")
                revs = {}
            for c in group:
                self._apply_revision(c, revs.get(c.nid), rnd)

    def _apply_revision(self, c: Case, r: Revision | None, rnd: int) -> None:
        if r and r.action == "accept_counter" and c.counter:
            spec = c.spec(teams=c.counter[0], duration=c.counter[1])
            if self._feasible(spec):
                self._h2h(c, c.borrower, c.lender, MessageType.ACCEPT, spec, r.reason, rnd, c.counter_mid)
                self._take(c, spec, "counter_accepted")
                return
        elif (r and r.action == "request_other" and rnd < MAX_NEGOTIATION_ROUNDS and r.lender_id in self.state.hospitals
              and 1 <= r.teams <= min(CFG.max_teams, c.uncovered)):
            dur = min(CFG.max_duration_min, max(CFG.min_duration_min, r.duration_min))
            spec = c.spec(r.lender_id, r.teams, dur)
            if r.lender_id != c.borrower and self._feasible(spec):
                c.round, c.lender, c.teams, c.duration, c.counter = rnd + 1, r.lender_id, r.teams, dur, None
                c.request_mid = self._h2h(c, c.borrower, c.lender, MessageType.REQUEST, spec, r.reason, c.round)
                self._note(c, f"hospital_coordination:{c.borrower}", "request_other", r.reason, c.lender)
                return
        c.escalated = True

    # ───────── Step 5: Resource Allocation arbitrates leftovers, then the fixed rule ─────────
    async def _arbitrate(self, cases: list[Case]) -> None:
        if not cases:
            return
        for c in cases:
            why = c.history[-1]["reason"] if c.history else "no agreement"
            c.escalate_mid = self._msg(c, H, c.borrower, RA, None, MessageType.ESCALATE, c.spec(), why, c.round, c.request_mid)
        payload = {"requests": [{"request_id": c.nid, "borrower_id": c.borrower, "care": c.cap.value, "urgency": c.urgency,
                                 "queued": len(c.serves), "history": c.history, "options": self._options(c)} for c in cases]}
        res = await ask_allocation(_dump(self.header, payload))
        self.sys._log_llm(self.t, RA, res)
        try:
            allocs = {a.request_id: a for a in Allocations.model_validate(res.output).allocations}
        except ValidationError:
            self._llm_failed("arbitration", "unparseable loan arbitration")
            allocs = {}
        for c in cases:
            a = allocs.get(c.nid)
            if a and a.lender_id != NO_ID and a.lender_id in self.state.hospitals and a.lender_id != c.borrower:
                dur = min(CFG.max_duration_min, max(CFG.min_duration_min, a.duration_min))
                spec = c.spec(a.lender_id, min(max(1, a.teams), c.uncovered, CFG.max_teams), dur)
                if self._feasible(spec):
                    self._msg(c, RA, None, H, c.borrower, MessageType.ACCEPT, spec, a.reason, c.round, c.escalate_mid)
                    self._take(c, spec, "arbitrated")

    def _fallback(self, cases: list[Case]) -> None:
        for c in cases:
            for opt in self._options(c):
                spec = c.spec(opt["hospital_id"], 1, c.duration)
                if self._rule_accepts(spec):
                    self.sys._record(self.t, "loan_fallback", stage="rule", negotiation_id=c.nid, lender_id=spec.lender_id)
                    self._msg(c, RA, None, H, c.borrower, MessageType.ACCEPT, spec, "fallback rule: nearest feasible lender",
                              c.round, c.escalate_mid or c.request_mid)
                    self._take(c, spec, "fallback")
                    break
