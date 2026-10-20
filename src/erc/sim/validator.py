"""The validation layer: every proposed physical action is checked here, and only here.

Agents and baselines propose; this module decides whether a proposal is
physically possible right now. It never modifies state, so it is safe to call
any number of times, and every rejection carries a reason code for logging.
"""
from __future__ import annotations

from erc.models.entities import Capability, Incident, UnitStatus, VictimStatus
from erc.models.messages import ActionType, ProposedAction, RejectionReason, ValidationResult
from erc.models.state import SimulationState

R = RejectionReason


def _ok() -> ValidationResult:
    return ValidationResult(accepted=True)


def _reject(reason: RejectionReason, detail: str) -> ValidationResult:
    return ValidationResult(accepted=False, reason=reason, detail=detail)


def feasible_destination_exists(state: SimulationState, caps: set[Capability]) -> bool:
    """True if at least one hospital can treat every capability in this ambulance load."""
    return any(all(h.can_treat(c) for c in caps) for h in state.hospitals.values())


def validate(action: ProposedAction, incident_id: str, state: SimulationState) -> ValidationResult:
    incident = state.incidents.get(incident_id)
    if incident is None or incident.arrival_time_min > state.time_min:
        return _reject(R.INCIDENT_NOT_ACTIVE, f"{incident_id} is unknown or has not arrived yet")
    if len(set(action.victim_ids)) != len(action.victim_ids):
        return _reject(R.MALFORMED, "Duplicate victim IDs in one action")
    checks = {
        ActionType.ASSIGN_AMBULANCE: _check_ambulance,
        ActionType.ASSIGN_RESPONDER: _check_responder,
        ActionType.ADMIT_PATIENT: _check_admission,
        ActionType.DIVERT_PATIENT: _check_admission,
    }
    return checks[action.action_type](action, incident, state)


def _check_ambulance(action: ProposedAction, incident: Incident, state: SimulationState) -> ValidationResult:
    amb = state.ambulances.get(action.ambulance_id)
    if amb is None:
        return _reject(R.UNKNOWN_RESOURCE, f"No ambulance {action.ambulance_id}")
    if not amb.is_available:
        return _reject(R.AMBULANCE_UNAVAILABLE, f"{amb.ambulance_id} is {amb.status.value}")
    if not action.victim_ids:
        return _reject(R.MALFORMED, "An ambulance assignment must name the victims to pick up")
    if len(action.victim_ids) > amb.capacity:
        return _reject(R.AMBULANCE_OVER_CAPACITY,
                       f"{amb.ambulance_id} holds {amb.capacity}, asked for {len(action.victim_ids)}")
    victims = {v.victim_id: v for v in incident.victims}
    caps: set[Capability] = set()
    for vid in action.victim_ids:
        v = victims.get(vid)
        if v is None:
            return _reject(R.UNKNOWN_RESOURCE, f"{vid} is not part of {incident.incident_id}")
        if v.status != VictimStatus.WAITING or vid in state.reservations:
            return _reject(R.VICTIM_UNAVAILABLE, f"{vid} is already assigned or being cared for")
        caps.add(v.required_capability)
    if not feasible_destination_exists(state, caps):
        needs = ", ".join(sorted(c.value for c in caps))
        return _reject(R.NO_FEASIBLE_DESTINATION, f"No hospital can treat this load together ({needs})")
    return _ok()


def _check_responder(action: ProposedAction, incident: Incident, state: SimulationState) -> ValidationResult:
    team = state.responders.get(action.responder_id)
    if team is None:
        return _reject(R.UNKNOWN_RESOURCE, f"No responder team {action.responder_id}")
    if not team.is_available:
        return _reject(R.RESPONDER_UNAVAILABLE, f"{team.team_id} is {team.status.value}")
    return _ok()


def _check_admission(action: ProposedAction, incident: Incident, state: SimulationState) -> ValidationResult:
    hospital = state.hospitals.get(action.hospital_id)
    if hospital is None:
        return _reject(R.UNKNOWN_RESOURCE, f"No hospital {action.hospital_id}")
    divert = action.action_type == ActionType.DIVERT_PATIENT
    victims = {v.victim_id: v for v in incident.victims}
    new_arrivals = 0
    for vid in action.victim_ids:
        v = victims.get(vid)
        if v is None:
            return _reject(R.UNKNOWN_RESOURCE, f"{vid} is not part of {incident.incident_id}")
        if vid not in state.reservations:
            return _reject(R.VICTIM_UNAVAILABLE, f"{vid} must be assigned to an ambulance first")
        if v.status not in (VictimStatus.WAITING, VictimStatus.IN_TRANSPORT):
            return _reject(R.VICTIM_UNAVAILABLE, f"{vid} has already reached a hospital")
        if not hospital.can_treat(v.required_capability):
            return _reject(R.HOSPITAL_LACKS_CAPABILITY,
                           f"{hospital.hospital_id} cannot treat {v.required_capability.value}")
        current = state.admissions.get(vid)
        if divert and (current is None or current == hospital.hospital_id):
            return _reject(R.MALFORMED, f"{vid} has no other admission to divert from")
        if not divert and current is not None:
            return _reject(R.MALFORMED, f"{vid} is already admitted to {current}; use divert")
        new_arrivals += 1

    # Routing: one ambulance carries its whole load to one hospital
    ambulance_ids = {state.reservations[vid] for vid in action.victim_ids}
    if len(ambulance_ids) > 1:
        return _reject(R.ROUTING_CONFLICT, "Victims in one admission must share an ambulance")
    amb_id = ambulance_ids.pop()
    if state.ambulances[amb_id].status == UnitStatus.TRANSPORTING:
        return _reject(R.ROUTING_CONFLICT, f"{amb_id} is already on its way to a hospital")
    for other, carrier in state.reservations.items():
        if carrier == amb_id and other not in action.victim_ids:
            current = state.admissions.get(other)
            if current is not None and current != hospital.hospital_id:
                return _reject(R.ROUTING_CONFLICT, f"Co-passenger {other} is going to {current}")

    load = hospital.er_occupied + state.incoming_count(hospital.hospital_id) + new_arrivals
    if load > hospital.er_capacity:
        return _reject(R.HOSPITAL_FULL,
                       f"{hospital.hospital_id} ER would hold {load} of {hospital.er_capacity}")
    return _ok()