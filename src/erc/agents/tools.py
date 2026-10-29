"""Function tools: the only way agents read the situation and submit proposals.

Situation views are built from validated state and ASSESSMENTS, never ground truth:
no deadlines, no hidden condition scores, no future incidents. Propose tools check each
proposal against the validator immediately and return feedback, so an agent can fix a
mistake in the same run. Accepted proposals go to the pool; nothing executes until
conflicts are resolved and the engine validates again.
"""
from __future__ import annotations

import json
import math

from agents import RunContextWrapper, function_tool
from pydantic import ValidationError

from erc.agents.context import AgentContext, Proposal
from erc.config import SETTINGS
from erc.models.entities import AmbulanceType, Capability, Hospital, Location, ResponderType
from erc.models.messages import ActionType, AgentName, ProposedAction
from erc.models.state import SimulationState
from erc.sim.validator import validate


def estimated_minutes(a: Location, b: Location) -> int:
    """Travel estimate without traffic (agents never see actual traffic)."""
    return math.ceil(a.distance_to(b) * 60 / SETTINGS.travel.ambulance_speed_kmh)


# ───────── Situation views (go into prompts) ─────────
def _victim_view(ctx: AgentContext, victim_id: str) -> dict | None:
    victim = ctx.state.find_victim(victim_id)
    report = ctx.assessments.get(victim.incident_id) if victim else None
    found = next((a for a in report.victims if a.victim_id == victim_id), None) if report else None
    if found is None:
        return None
    return {"victim_id": victim_id, "urgency": int(found.severity),
            "care": found.required_capability.value, "needs_als": found.needs_als}


def _hospital_view(s: SimulationState, h: Hospital) -> dict:
    return {"hospital_id": h.hospital_id, "name": h.name,
            "treats": [c.value for c, n in h.treatment_slots.items() if n > 0],
            "er_patients_plus_incoming": h.er_occupied + s.incoming_count(h.hospital_id),
            "er_capacity": h.er_capacity,
            "free_treatment_slots": {c.value: h.free_slots(c) for c in h.treatment_slots},
            "free_beds": h.beds - h.beds_occupied}


def dispatch_situation(ctx: AgentContext) -> dict:
    s = ctx.state
    free_amb = s.available_ambulances()
    assigned_teams: dict[str, set[str]] = {}
    for r in s.responders.values():
        if r.assigned_incident:
            assigned_teams.setdefault(r.assigned_incident, set()).add(r.responder_type.value)
    groups: dict[str, list[dict]] = {}
    for v in s.waiting_victims():
        view = _victim_view(ctx, v.victim_id)
        if view:
            groups.setdefault(v.incident_id, []).append(view)
    incidents = []
    for iid, victims in groups.items():
        inc, report = s.incidents[iid], ctx.assessments.get(iid)
        nearest = sorted(free_amb, key=lambda a: (a.location.distance_to(inc.location), a.ambulance_id))[:3]
        incidents.append({
            "incident_id": iid,
            "minutes_since_reported": s.time_min - inc.arrival_time_min,
            "team_needed": report.required_responder.value if report and report.required_responder else "none",
            "teams_assigned": sorted(assigned_teams.get(iid, set())),
            "waiting_victims": victims,
            "nearest_free_ambulances": [
                {"ambulance_id": a.ambulance_id, "type": "ALS" if a.ambulance_type == AmbulanceType.ALS else "BLS",
                 "est_minutes": estimated_minutes(a.location, inc.location)} for a in nearest],
        })
    incidents.sort(key=lambda i: (-max(v["urgency"] for v in i["waiting_victims"]),
                                  -i["minutes_since_reported"], i["incident_id"]))

    def relevant(team_type: str, incident: dict) -> bool:
        if team_type == ResponderType.MEDICAL.value:
            return any(v["urgency"] >= 4 for v in incident["waiting_victims"])
        return incident["team_needed"] == team_type

    teams = [{"team_id": r.team_id, "type": r.responder_type.value,
              "est_minutes_to": {i["incident_id"]: estimated_minutes(r.location, s.incidents[i["incident_id"]].location)
                                 for i in incidents if relevant(r.responder_type.value, i)}}
             for r in s.available_responders()]
    return {"time_min": s.time_min, "ambulance_capacity": SETTINGS.env.ambulance_capacity,
            "free_ambulances": [{"ambulance_id": a.ambulance_id,
                                 "type": "ALS" if a.ambulance_type == AmbulanceType.ALS else "BLS"}
                                for a in free_amb],
            "incidents": incidents, "free_teams": teams}


def hospital_situation(ctx: AgentContext) -> dict:
    s = ctx.state
    by_amb: dict[str, list[str]] = {}
    for vid, aid in s.reservations.items():
        if vid not in s.admissions:
            by_amb.setdefault(aid, []).append(vid)
    awaiting = []
    for aid, vids in sorted(by_amb.items()):
        amb = s.ambulances[aid]
        views = [v for vid in vids if (v := _victim_view(ctx, vid))]
        cares = {Capability(v["care"]) for v in views}
        origin = s.incidents[amb.assigned_incident].location if amb.assigned_incident else amb.location
        awaiting.append({"ambulance_id": aid, "ambulance_status": amb.status.value, "victims": views,
                         "est_minutes_to": {h.hospital_id: estimated_minutes(origin, h.location)
                                            for h in s.hospitals.values() if all(h.can_treat(c) for c in cares)}})
    return {"time_min": s.time_min, "ambulances_needing_destination": awaiting,
            "hospitals": [_hospital_view(s, h) for h in s.hospitals.values()]}


def waiting_critical_view(ctx: AgentContext, limit: int = 8) -> list[dict]:
    """Assessed critical victims (urgency 4-5) still waiting for an ambulance, with minutes to each capable hospital."""
    s, out = ctx.state, []
    for v in s.waiting_victims():
        view = _victim_view(ctx, v.victim_id)
        if v.victim_id in s.reservations or view is None or view["urgency"] < 4:
            continue
        loc = s.incidents[v.incident_id].location
        out.append({**view, "est_minutes_to": {h.hospital_id: estimated_minutes(loc, h.location)
                                               for h in s.hospitals.values() if h.can_treat(Capability(view["care"]))}})
    out.sort(key=lambda x: (-x["urgency"], x["victim_id"]))
    return out[:limit]


def hospital_review_view(ctx: AgentContext, requests: list[dict], held: dict[str, int]) -> dict:
    """What Hospital Coordination sees when reviewing admission requests: ER load including beds already
    promised (en route, or accepted earlier in this review), and assessed critical victims still waiting.
    Never deadlines or ground truth."""
    s = ctx.state
    hospitals = []
    for h in s.hospitals.values():
        view = _hospital_view(s, h)
        view["er_patients_plus_incoming"] += held.get(h.hospital_id, 0)
        hospitals.append(view)
    return {"time_min": s.time_min, "requests": requests, "hospitals": hospitals,
            "waiting_critical": waiting_critical_view(ctx)}


# ───────── Shared submission logic ─────────
def _reject(ctx: AgentContext, tool: str, args: dict, reason: str, detail: str) -> str:
    ctx.invalid.append({"time_min": ctx.state.time_min, "tool": tool, "args": args,
                        "reason": reason, "detail": detail})
    return f"REJECTED ({reason}): {detail}. Correct it and submit again if still appropriate."


def _build(ctx: AgentContext, tool: str, args: dict, **fields) -> ProposedAction | str:
    try:
        return ProposedAction(**fields)
    except ValidationError as e:
        return _reject(ctx, tool, args, "malformed", e.errors()[0]["msg"])


def _to_pool(ctx: AgentContext, proposer: AgentName, tool: str, args: dict, incident_id: str,
             action: ProposedAction, priority: int, reason: str) -> str:
    for p in ctx.proposals:
        if p.proposer == proposer and p.incident_id == incident_id and p.action == action:
            return f"Already in the proposal pool as {p.proposal_id}; no need to resubmit."
    result = validate(action, incident_id, ctx.state)
    if not result.accepted:
        return _reject(ctx, tool, args, result.reason.value, result.detail)
    pid = ctx.next_proposal_id()
    ctx.proposals.append(Proposal(proposal_id=pid, proposer=proposer, incident_id=incident_id, action=action,
                                  priority=min(5, max(1, int(priority))), reason=(reason or "-")[:300],
                                  time_min=ctx.state.time_min))
    return f"ACCEPTED into the proposal pool as {pid}. It executes only after conflict checks and final validation."


# ───────── Tool logic (plain functions, testable without an LLM) ─────────
def propose_ambulance(ctx: AgentContext, ambulance_id: str, incident_id: str, victim_ids: list[str],
                      priority: int, reason: str) -> str:
    tool = "submit_ambulance_assignment"
    args = dict(ambulance_id=ambulance_id, incident_id=incident_id, victim_ids=list(victim_ids))
    action = _build(ctx, tool, args, action_type=ActionType.ASSIGN_AMBULANCE,
                    ambulance_id=ambulance_id, victim_ids=list(victim_ids))
    if isinstance(action, str):
        return action
    return _to_pool(ctx, AgentName.DISPATCH, tool, args, incident_id, action, priority, reason)


def propose_team(ctx: AgentContext, team_id: str, incident_id: str, reason: str) -> str:
    tool, args = "submit_team_assignment", dict(team_id=team_id, incident_id=incident_id)
    action = _build(ctx, tool, args, action_type=ActionType.ASSIGN_RESPONDER, responder_id=team_id)
    if isinstance(action, str):
        return action
    return _to_pool(ctx, AgentName.DISPATCH, tool, args, incident_id, action, 3, reason)


def propose_admission(ctx: AgentContext, hospital_id: str, victim_ids: list[str], reason: str,
                      divert: bool = False) -> str:
    tool = "submit_diversion" if divert else "submit_admission"
    args = dict(hospital_id=hospital_id, victim_ids=list(victim_ids))
    if not victim_ids:
        return _reject(ctx, tool, args, "malformed", "victim_ids is empty")
    victim = ctx.state.find_victim(victim_ids[0])
    if victim is None:
        return _reject(ctx, tool, args, "unknown_resource", f"No visible victim {victim_ids[0]}")
    action = _build(ctx, tool, args, action_type=ActionType.DIVERT_PATIENT if divert else ActionType.ADMIT_PATIENT,
                    hospital_id=hospital_id, victim_ids=list(victim_ids))
    if isinstance(action, str):
        return action
    urgencies = [v["urgency"] for vid in victim_ids if (v := _victim_view(ctx, vid))]
    priority = 6 - max(urgencies) if urgencies else 3
    return _to_pool(ctx, AgentName.HOSPITAL, tool, args, victim.incident_id, action, priority, reason)


def propose_destination(ctx: AgentContext, hospital_id: str, victim_ids: list[str], reason: str) -> str:
    """Dispatch's admission request (v2): it goes to Hospital Coordination for review, not to the pool."""
    tool, args = "submit_admission_request", dict(hospital_id=hospital_id, victim_ids=list(victim_ids))
    if not victim_ids:
        return _reject(ctx, tool, args, "malformed", "victim_ids is empty")
    victim = ctx.state.find_victim(victim_ids[0])
    if victim is None:
        return _reject(ctx, tool, args, "unknown_resource", f"No visible victim {victim_ids[0]}")
    action = _build(ctx, tool, args, action_type=ActionType.ADMIT_PATIENT, hospital_id=hospital_id,
                    victim_ids=list(victim_ids))
    if isinstance(action, str):
        return action
    urgencies = [v["urgency"] for vid in victim_ids if (v := _victim_view(ctx, vid))]
    return _to_pool(ctx, AgentName.DISPATCH, tool, args, victim.incident_id, action,
                    6 - max(urgencies) if urgencies else 3, reason)


def _locate(s: SimulationState, place_id: str) -> Location | None:
    if place_id in s.ambulances:
        return s.ambulances[place_id].location
    if place_id in s.responders:
        return s.responders[place_id].location
    if place_id in s.hospitals:
        return s.hospitals[place_id].location
    inc = s.incidents.get(place_id)
    return inc.location if inc is not None and inc.arrival_time_min <= s.time_min else None


def travel_minutes(ctx: AgentContext, from_id: str, to_id: str) -> str:
    a, b = _locate(ctx.state, from_id), _locate(ctx.state, to_id)
    if a is None or b is None:
        return f"Unknown ID: {from_id if a is None else to_id}"
    return json.dumps({"from": from_id, "to": to_id, "est_minutes": estimated_minutes(a, b),
                       "note": "estimate without traffic"})


def hospital_detail(ctx: AgentContext, hospital_id: str) -> str:
    h = ctx.state.hospitals.get(hospital_id)
    return json.dumps(_hospital_view(ctx.state, h)) if h else f"Unknown hospital: {hospital_id}"


# ───────── SDK function tools (thin wrappers) ─────────
@function_tool
def estimate_travel_minutes(ctx: RunContextWrapper[AgentContext], from_id: str, to_id: str) -> str:
    """Estimate driving time in minutes (without traffic) between two places.

    Args:
        from_id: An ambulance, team, hospital, or incident ID.
        to_id: An ambulance, team, hospital, or incident ID.
    """
    return travel_minutes(ctx.context, from_id, to_id)


@function_tool
def hospital_status(ctx: RunContextWrapper[AgentContext], hospital_id: str) -> str:
    """Current ER load, free treatment slots by care type, and free beds for one hospital.

    Args:
        hospital_id: A hospital ID such as H-T.
    """
    return hospital_detail(ctx.context, hospital_id)


@function_tool
def submit_ambulance_assignment(ctx: RunContextWrapper[AgentContext], ambulance_id: str, incident_id: str,
                                victim_ids: list[str], priority: int, reason: str) -> str:
    """Propose sending one free ambulance to pick up specific waiting victims at one incident.

    Args:
        ambulance_id: A currently free ambulance, e.g. AMB-01.
        incident_id: The incident the victims belong to.
        victim_ids: Victims to pick up (at most the ambulance capacity), all from this incident.
        priority: Your urgency for this proposal, 1 (highest) to 5 (lowest).
        reason: One short sentence explaining the choice.
    """
    return propose_ambulance(ctx.context, ambulance_id, incident_id, victim_ids, priority, reason)


@function_tool
def submit_team_assignment(ctx: RunContextWrapper[AgentContext], team_id: str, incident_id: str, reason: str) -> str:
    """Propose sending a free fire, rescue, or medical team to an incident.

    Args:
        team_id: A currently free team, e.g. RESCUE-1.
        incident_id: The incident to send it to.
        reason: One short sentence explaining the choice.
    """
    return propose_team(ctx.context, team_id, incident_id, reason)


@function_tool
def submit_admission(ctx: RunContextWrapper[AgentContext], hospital_id: str, victim_ids: list[str], reason: str) -> str:
    """Propose the destination hospital for all victims carried by one ambulance.

    Args:
        hospital_id: The hospital that should receive them.
        victim_ids: Every victim assigned to that ambulance.
        reason: One short sentence explaining the choice.
    """
    return propose_admission(ctx.context, hospital_id, victim_ids, reason)


@function_tool
def submit_diversion(ctx: RunContextWrapper[AgentContext], hospital_id: str, victim_ids: list[str], reason: str) -> str:
    """Propose redirecting already-admitted victims (not yet transporting) to a different hospital.

    Args:
        hospital_id: The new destination hospital.
        victim_ids: Every victim assigned to that ambulance.
        reason: One short sentence explaining the choice.
    """
    return propose_admission(ctx.context, hospital_id, victim_ids, reason, divert=True)


@function_tool
def submit_admission_request(ctx: RunContextWrapper[AgentContext], hospital_id: str, victim_ids: list[str],
                             reason: str) -> str:
    """Request a destination hospital for all victims carried by one ambulance. Hospital Coordination reviews it.

    Args:
        hospital_id: The hospital you want to receive them.
        victim_ids: Every victim assigned to that ambulance.
        reason: One short sentence explaining the choice.
    """
    return propose_destination(ctx.context, hospital_id, victim_ids, reason)


DISPATCH_TOOLS = [estimate_travel_minutes, submit_ambulance_assignment, submit_team_assignment]
HOSPITAL_TOOLS = [hospital_status, estimate_travel_minutes, submit_admission, submit_diversion]
DESTINATION_TOOLS = [hospital_status, estimate_travel_minutes, submit_admission_request]