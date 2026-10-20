"""Conflict detection and the fixed priority rule.

detect_conflicts() is pure: no LLM, no state changes, no winners chosen. It finds groups of
proposals that cannot all execute together. resolve_by_priority() is the fixed rule used by the
no-negotiation system, and the fallback when negotiation does not converge.
"""
from __future__ import annotations

from collections import defaultdict
from enum import Enum

from pydantic import BaseModel

from erc.agents.context import AgentContext, Proposal
from erc.models.entities import VictimStatus
from erc.models.messages import ActionType
from erc.models.state import SimulationState

ADMISSIONS = (ActionType.ADMIT_PATIENT, ActionType.DIVERT_PATIENT)


class ConflictType(str, Enum):
    RESOURCE = "resource"    # proposals claim the same ambulance, team, or victim
    CAPACITY = "capacity"    # admissions that together would overfill an ER
    ROUTING = "routing"      # one ambulance's victims sent to different hospitals


class Conflict(BaseModel):
    conflict_id: str
    conflict_type: ConflictType
    proposal_ids: list[str]
    resources: list[str]
    incident_ids: list[str]
    reason: str


def claimed_keys(p: Proposal) -> set[str]:
    a = p.action
    if a.action_type == ActionType.ASSIGN_AMBULANCE:
        return {f"ambulance:{a.ambulance_id}"} | {f"victim:{v}" for v in a.victim_ids}
    if a.action_type == ActionType.ASSIGN_RESPONDER:
        return {f"team:{a.responder_id}"}
    return {f"admit:{v}" for v in a.victim_ids}


def detect_conflicts(proposals: list[Proposal], state: SimulationState, round_id: str = "R") -> list[Conflict]:
    by_id = {p.proposal_id: p for p in proposals}
    conflicts: list[Conflict] = []

    def add(kind: ConflictType, members: list[str], resources: list[str], reason: str) -> None:
        conflicts.append(Conflict(conflict_id=f"{round_id}-C{len(conflicts) + 1:02d}", conflict_type=kind,
                                  proposal_ids=sorted(members), resources=sorted(resources),
                                  incident_ids=sorted({by_id[m].incident_id for m in members}), reason=reason))

    # 1. Resource: connected groups of proposals sharing any claimed key
    keys = {p.proposal_id: claimed_keys(p) for p in proposals}
    parent = {pid: pid for pid in keys}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: dict[str, str] = {}
    for pid, ks in keys.items():
        for k in sorted(ks):
            if k in owner:
                parent[find(pid)] = find(owner[k])
            else:
                owner[k] = pid
    groups: dict[str, list[str]] = defaultdict(list)
    for pid in keys:
        groups[find(pid)].append(pid)
    for members in groups.values():
        if len(members) > 1:
            shared = sorted(k for k in set().union(*(keys[m] for m in members))
                            if sum(k in keys[m] for m in members) > 1)
            add(ConflictType.RESOURCE, members, shared, f"{len(members)} proposals claim {', '.join(shared)}")

    admissions = [p for p in proposals if p.action.action_type in ADMISSIONS]

    # 2. Routing: one ambulance's victims sent to different hospitals
    by_amb: dict[str, list[Proposal]] = defaultdict(list)
    for p in admissions:
        amb = state.reservations.get(p.action.victim_ids[0])
        if amb:
            by_amb[amb].append(p)
    for amb, ps in by_amb.items():
        hospitals = sorted({p.action.hospital_id for p in ps})
        if len(hospitals) > 1:
            add(ConflictType.ROUTING, [p.proposal_id for p in ps], [f"ambulance:{amb}"],
                f"{amb}'s victims proposed for {', '.join(hospitals)}")

    # 3. Capacity: admissions to one hospital that together exceed its ER
    by_hosp: dict[str, list[Proposal]] = defaultdict(list)
    for p in admissions:
        by_hosp[p.action.hospital_id].append(p)
    for hid, ps in by_hosp.items():
        if len(ps) < 2:
            continue
        h = state.hospitals[hid]
        load = h.er_occupied + state.incoming_count(hid) + sum(len(p.action.victim_ids) for p in ps)
        if load > h.er_capacity:
            add(ConflictType.CAPACITY, [p.proposal_id for p in ps], [f"er:{hid}"],
                f"{hid} ER would hold {load} of {h.er_capacity}")
    return conflicts


# ───────── Fixed priority rule (no-negotiation system and negotiation fallback) ─────────
def _assessed_severities(p: Proposal, ctx: AgentContext) -> list[int]:
    s = ctx.state
    victim_ids = p.action.victim_ids or [v.victim_id for v in s.incidents[p.incident_id].victims
                                         if v.status == VictimStatus.WAITING]
    report = ctx.assessments.get(p.incident_id)
    found = {a.victim_id: int(a.severity) for a in report.victims} if report else {}
    return [found[v] for v in victim_ids if v in found]


def priority_key(p: Proposal, ctx: AgentContext) -> tuple:
    """Highest assessed severity, then more critical victims, then longest waiting, then proposal ID."""
    sev = _assessed_severities(p, ctx)
    waited = ctx.state.time_min - ctx.state.incidents[p.incident_id].arrival_time_min
    return (-max(sev, default=0), -sum(x >= 4 for x in sev), -waited, p.proposal_id)


def resolve_by_priority(conflict: Conflict, ctx: AgentContext) -> list[str]:
    """Returns the winning proposal IDs. Deterministic and transparent; never uses LLM scores."""
    by_id = {p.proposal_id: p for p in ctx.proposals}
    members = sorted((by_id[pid] for pid in conflict.proposal_ids), key=lambda p: priority_key(p, ctx))
    winners: list[Proposal] = []
    if conflict.conflict_type == ConflictType.CAPACITY:
        hid = members[0].action.hospital_id
        h = ctx.state.hospitals[hid]
        room = h.er_capacity - h.er_occupied - ctx.state.incoming_count(hid)
        for p in members:
            if len(p.action.victim_ids) <= room:
                winners.append(p)
                room -= len(p.action.victim_ids)
    elif conflict.conflict_type == ConflictType.ROUTING:
        target = members[0].action.hospital_id
        winners = [p for p in members if p.action.hospital_id == target]
    else:
        taken: set[str] = set()
        for p in members:
            ks = claimed_keys(p)
            if not ks & taken:
                winners.append(p)
                taken |= ks
    return [p.proposal_id for p in winners]