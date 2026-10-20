"""Discrete-time simulation engine: the only code that changes the world.

Every minute:
  1. reveal incidents whose arrival time has come
  2. advance responders, ambulances, and treatments whose timers are due
  3. ask the policy for decisions, only if the decision situation changed
  4. validate each decision (in the validator), then apply it or log the rejection
  5. deteriorate every victim not yet in treatment
  6. start treatments where a slot, a bed, and qualified staff are free
  7. record a snapshot
The policy (a baseline or the agent system) only ever proposes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from erc.config import SETTINGS
from erc.logging.event_log import EventLog
from erc.models.entities import (
    AmbulanceType, Capability, ResponderType, SkillLevel, StaffMember, StaffRole,
    UnitStatus, Victim, VictimStatus,
)
from erc.models.messages import ActionType, ProposedAction
from erc.models.state import Scenario, SimulationState
from erc.sim.deterioration import deteriorate, is_deteriorated
from erc.sim.travel import travel_time_min
from erc.sim.validator import validate


# ───────── What a policy hands to the engine ─────────
@dataclass
class Decision:
    action: ProposedAction
    incident_id: str
    source: str = "policy"
    message_id: str | None = None


class Policy(Protocol):
    name: str

    def decide(self, state: SimulationState) -> list[Decision]: ...


# ───────── Internal timers (owned by the engine, invisible to policies) ─────────
@dataclass
class AmbulanceJob:
    incident_id: str
    victim_ids: list[str]
    phase: str                     # to_scene -> on_scene -> to_hospital -> handover
    ready_at: int
    arrived_scene_at: int | None = None
    hospital_id: str | None = None


@dataclass
class ResponderJob:
    incident_id: str
    arrive_at: int
    on_scene: bool = False


@dataclass
class TreatmentJob:
    hospital_id: str
    capability: Capability
    doctor_id: str
    nurse_id: str
    ends_at: int


class Engine:
    def __init__(self, scenario: Scenario, policy: Policy, log: EventLog | None = None) -> None:
        self.state = SimulationState.from_scenario(scenario)
        self.policy = policy
        self.log = log or EventLog(f"{scenario.name.value}_seed{scenario.seed}_{policy.name}")
        self.amb_jobs: dict[str, AmbulanceJob] = {}
        self.resp_jobs: dict[str, ResponderJob] = {}
        self.treatments: dict[str, TreatmentJob] = {}
        self.policy_calls = 0
        self._last_signature: tuple | None = None

    # ───────── Main loop ─────────
    def run(self) -> SimulationState:
        step = SETTINGS.env.time_step_min
        for t in range(0, SETTINGS.env.duration_min + 1, step):
            self.state.time_min = t
            self._reveal_incidents(t)
            self._advance_responders(t)
            self._advance_ambulances(t)
            self._finish_treatments(t)
            signature = self._decision_signature()
            if signature is not None and signature != self._last_signature:
                self.policy_calls += 1
                self.log.record(t, "policy_called", call=self.policy_calls)
                for decision in self.policy.decide(self.state):
                    self._handle(decision)
                self._last_signature = self._decision_signature()
            self._deteriorate_all(step)
            self._start_treatments(t)
            self.log.record(t, "snapshot", **self.state.summary())
        self._close_out()
        return self.state

    # ───────── Decisions ─────────
    def _decision_signature(self) -> tuple | None:
        """Describes the decision situation. None means there is nothing to decide."""
        s = self.state
        waiting = tuple(sorted(v.victim_id for v in s.waiting_victims()))
        free_amb = tuple(sorted(a.ambulance_id for a in s.available_ambulances()))
        free_resp = tuple(sorted(r.team_id for r in s.available_responders()))
        awaiting_dest = tuple(sorted(
            aid for aid, job in self.amb_jobs.items()
            if job.phase == "on_scene" and s.ambulances[aid].victims_onboard and self._destination(job) is None))
        er = tuple((h.hospital_id, h.er_occupied, s.incoming_count(h.hospital_id)) for h in s.hospitals.values())
        has_work = (waiting and free_amb) or awaiting_dest or self._responder_needed()
        return (waiting, free_amb, free_resp, awaiting_dest, er) if has_work else None

    def _responder_needed(self) -> bool:
        s = self.state
        covered = {r.assigned_incident for r in s.responders.values() if r.assigned_incident}
        free_types = {r.responder_type for r in s.available_responders()}
        return any(
            inc.required_responder in free_types and inc.incident_id not in covered
            and any(v.status == VictimStatus.WAITING for v in inc.victims)
            for inc in s.visible_incidents() if inc.required_responder is not None)

    def _handle(self, d: Decision) -> None:
        result = validate(d.action, d.incident_id, self.state)
        payload = dict(incident_id=d.incident_id, source=d.source, message_id=d.message_id,
                       action=d.action.model_dump(mode="json"))
        if not result.accepted:
            self.log.record(self.state.time_min, "action_rejected",
                            reason=result.reason.value, detail=result.detail, **payload)
            return
        self._apply(d)
        self.log.record(self.state.time_min, "action_accepted", **payload)

    def _apply(self, d: Decision) -> None:
        a, t, s = d.action, self.state.time_min, self.state
        incident = s.incidents[d.incident_id]
        if a.action_type == ActionType.ASSIGN_AMBULANCE:
            amb = s.ambulances[a.ambulance_id]
            eta = t + travel_time_min(s.seed, amb.location, incident.location, t)
            amb.status = UnitStatus.EN_ROUTE
            amb.assigned_incident = d.incident_id
            for vid in a.victim_ids:
                s.reservations[vid] = amb.ambulance_id
            self.amb_jobs[amb.ambulance_id] = AmbulanceJob(d.incident_id, list(a.victim_ids), "to_scene", eta)
        elif a.action_type == ActionType.ASSIGN_RESPONDER:
            team = s.responders[a.responder_id]
            eta = t + travel_time_min(s.seed, team.location, incident.location, t)
            team.status = UnitStatus.EN_ROUTE
            team.assigned_incident = d.incident_id
            self.resp_jobs[team.team_id] = ResponderJob(d.incident_id, eta)
        else:  # ADMIT or DIVERT
            for vid in a.victim_ids:
                s.admissions[vid] = a.hospital_id

    # ───────── Movement ─────────
    def _reveal_incidents(self, t: int) -> None:
        for inc in self.state.incidents.values():
            if inc.arrival_time_min == t:
                self.log.record(t, "incident_arrived", incident_id=inc.incident_id,
                                victims=inc.victim_count, max_severity=int(inc.max_severity))

    def _advance_responders(self, t: int) -> None:
        s = self.state
        for tid, job in list(self.resp_jobs.items()):
            team, inc = s.responders[tid], s.incidents[job.incident_id]
            if not job.on_scene and t >= job.arrive_at:
                job.on_scene = True
                team.status = UnitStatus.ON_SCENE
                team.location = inc.location.model_copy()
                if team.responder_type == ResponderType.MEDICAL:
                    for v in inc.victims:
                        if v.status == VictimStatus.WAITING:
                            s.first_contact_min.setdefault(v.victim_id, t)
                self.log.record(t, "responder_arrived", team_id=tid, incident_id=job.incident_id)
            if job.on_scene and all(v.status != VictimStatus.WAITING for v in inc.victims):
                team.assigned_incident = None
                team.status = UnitStatus.AVAILABLE
                del self.resp_jobs[tid]
                self.log.record(t, "responder_released", team_id=tid, incident_id=job.incident_id)

    def _advance_ambulances(self, t: int) -> None:
        s, travel = self.state, SETTINGS.travel
        for aid, job in list(self.amb_jobs.items()):
            amb, inc = s.ambulances[aid], s.incidents[job.incident_id]
            victims = [s.find_victim(v) for v in job.victim_ids]
            if job.phase == "to_scene" and t >= job.ready_at:
                job.phase, job.arrived_scene_at = "on_scene", t
                amb.status = UnitStatus.ON_SCENE
                amb.location = inc.location.model_copy()
                for v in victims:
                    s.first_contact_min.setdefault(v.victim_id, t)
                self.log.record(t, "ambulance_on_scene", ambulance_id=aid, incident_id=job.incident_id)
            if job.phase == "on_scene":
                ready = job.arrived_scene_at + travel.on_scene_time_min
                if inc.required_responder is not None and not self._team_on_scene(job.incident_id):
                    ready += travel.extrication_delay_min
                if t >= ready and not amb.victims_onboard:
                    amb.victims_onboard = list(job.victim_ids)
                    for v in victims:
                        v.status = VictimStatus.IN_TRANSPORT
                    self.log.record(t, "victims_loaded", ambulance_id=aid, victim_ids=job.victim_ids)
                hospital_id = self._destination(job)
                if amb.victims_onboard and hospital_id is not None:
                    hospital = s.hospitals[hospital_id]
                    job.phase, job.hospital_id = "to_hospital", hospital_id
                    job.ready_at = t + travel_time_min(s.seed, inc.location, hospital.location, t)
                    amb.status = UnitStatus.TRANSPORTING
                    self.log.record(t, "ambulance_departed", ambulance_id=aid, hospital_id=hospital_id)
            if job.phase == "to_hospital" and t >= job.ready_at:
                job.phase, job.ready_at = "handover", t + travel.handover_time_min
                amb.location = s.hospitals[job.hospital_id].location.model_copy()
                self.log.record(t, "ambulance_at_hospital", ambulance_id=aid, hospital_id=job.hospital_id)
            if job.phase == "handover" and t >= job.ready_at:
                hospital = s.hospitals[job.hospital_id]
                for v in victims:
                    v.status = VictimStatus.AWAITING_TREATMENT
                    s.reservations.pop(v.victim_id, None)
                hospital.er_occupied += len(victims)
                amb.victims_onboard = []
                amb.assigned_incident = None
                amb.status = UnitStatus.AVAILABLE
                del self.amb_jobs[aid]
                self.log.record(t, "handover_complete", ambulance_id=aid, hospital_id=job.hospital_id,
                                victim_ids=job.victim_ids)

    def _destination(self, job: AmbulanceJob) -> str | None:
        hospitals = {self.state.admissions.get(v) for v in job.victim_ids}
        return hospitals.pop() if len(hospitals) == 1 and None not in hospitals else None

    def _team_on_scene(self, incident_id: str, kind: ResponderType | None = None) -> bool:
        return any(
            job.incident_id == incident_id and job.on_scene
            and (kind is None or self.state.responders[tid].responder_type == kind)
            for tid, job in self.resp_jobs.items())

    # ───────── Patients ─────────
    def _care_factor(self, v: Victim) -> float:
        d, s = SETTINGS.deterioration, self.state
        if v.status == VictimStatus.AWAITING_TREATMENT:
            return d.als_care_factor
        factors = [1.0]
        aid = s.reservations.get(v.victim_id)
        job = self.amb_jobs.get(aid) if aid else None
        if job is not None and job.phase != "to_scene":
            als = s.ambulances[aid].ambulance_type == AmbulanceType.ALS
            factors.append(d.als_care_factor if als else d.bls_care_factor)
        if v.status == VictimStatus.WAITING and self._team_on_scene(v.incident_id, ResponderType.MEDICAL):
            factors.append(d.bls_care_factor)
        return min(factors)

    def _deteriorate_all(self, minutes: int) -> None:
        for v in self.state.victims():
            if v.status in (VictimStatus.IN_TREATMENT, VictimStatus.TREATED):
                continue
            was_ok = not is_deteriorated(v)
            deteriorate(v, minutes, self._care_factor(v))
            if was_ok and is_deteriorated(v):
                self.log.record(self.state.time_min, "victim_deteriorated", victim_id=v.victim_id,
                                severity=int(v.severity))

    def _free_staff(self, hospital_id: str, role: StaffRole, cap: Capability,
                    minimum: SkillLevel) -> StaffMember | None:
        options = [m for m in self.state.staff.values()
                   if m.hospital_id == hospital_id and m.role == role
                   and m.is_available and m.is_qualified(cap, minimum)]
        return min(options, key=lambda m: (m.current_patients, m.staff_id), default=None)

    def _start_treatments(self, t: int) -> None:
        s = self.state
        queue = [v for v in s.victims() if v.status == VictimStatus.AWAITING_TREATMENT]
        queue.sort(key=lambda v: (-int(v.severity), v.condition, v.victim_id))
        for v in queue:
            h, cap = s.hospitals[s.admissions[v.victim_id]], v.required_capability
            if h.free_slots(cap) <= 0 or h.beds_occupied >= h.beds:
                continue
            doctor = self._free_staff(h.hospital_id, StaffRole.DOCTOR, cap, SkillLevel.INTERMEDIATE)
            nurse = self._free_staff(h.hospital_id, StaffRole.NURSE, cap, SkillLevel.BASIC)
            if doctor is None or nurse is None:
                continue
            doctor.current_patients += 1
            nurse.current_patients += 1
            h.treatment_occupied = {**h.treatment_occupied, cap: h.treatment_occupied.get(cap, 0) + 1}
            h.er_occupied -= 1
            h.beds_occupied += 1
            v.status = VictimStatus.IN_TREATMENT
            s.treatment_start_min[v.victim_id] = t
            ends = t + SETTINGS.treatment.duration_min[int(v.severity)]
            self.treatments[v.victim_id] = TreatmentJob(h.hospital_id, cap, doctor.staff_id, nurse.staff_id, ends)
            self.log.record(t, "treatment_started", victim_id=v.victim_id, hospital_id=h.hospital_id,
                            doctor_id=doctor.staff_id, nurse_id=nurse.staff_id)

    def _finish_treatments(self, t: int) -> None:
        s = self.state
        for vid, job in list(self.treatments.items()):
            if t < job.ends_at:
                continue
            s.find_victim(vid).status = VictimStatus.TREATED
            h = s.hospitals[job.hospital_id]
            h.treatment_occupied = {**h.treatment_occupied, job.capability: h.treatment_occupied[job.capability] - 1}
            s.staff[job.doctor_id].current_patients -= 1
            s.staff[job.nurse_id].current_patients -= 1
            del self.treatments[vid]
            self.log.record(t, "treatment_finished", victim_id=vid, hospital_id=job.hospital_id)

    def _close_out(self) -> None:
        for v in self.state.victims():
            if v.status == VictimStatus.WAITING:
                v.status = VictimStatus.UNSERVED
        self.log.record(self.state.time_min, "run_finished", policy=self.policy.name,
                        policy_calls=self.policy_calls,
                        rejected=len(self.log.of_kind("action_rejected")))