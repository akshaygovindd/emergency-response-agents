"""Baseline 2 (greedy): a strong centralized heuristic with full current information.

Prioritises victims who can still be saved, ordered by remaining slack before
their deadline; matches ALS ambulances to critical victims; sends rescue, fire,
and medical teams to the most urgent incidents first; and routes patients to
the capable hospital with the best mix of distance and ER load. It sees what
the agents see (estimated travel from distance, no future incidents) but it
cannot negotiate or interpret text reports.
"""
from __future__ import annotations

from erc.config import SETTINGS
from erc.models.entities import Ambulance, AmbulanceType, Capability, Incident, ResponderType, Victim, VictimStatus
from erc.models.messages import ActionType, ProposedAction
from erc.models.state import SimulationState
from erc.sim.engine import Decision

ALS_TOLERANCE_KM = 5.0   # accept a slightly farther unit of the right type
LOAD_PENALTY_KM = 10.0   # distance-equivalent cost of a completely full ER


def estimated_minutes(distance_km: float) -> float:
    """Travel estimate without traffic: the same information agents get."""
    return distance_km * 60 / SETTINGS.travel.ambulance_speed_kmh


class GreedyPolicy:
    name = "greedy"

    def decide(self, state: SimulationState) -> list[Decision]:
        return self._ambulances(state) + self._responders(state) + self._admissions(state)

    # ───────── Urgency ─────────
    @staticmethod
    def _slack(v: Victim, inc: Incident, state: SimulationState, free: list[Ambulance]) -> float:
        nearest = min((a.location.distance_to(inc.location) for a in free), default=0.0)
        return inc.arrival_time_min + v.deadline_min - state.time_min - estimated_minutes(nearest)

    def _priority(self, v: Victim, inc: Incident, state: SimulationState, free: list[Ambulance]) -> tuple:
        slack = self._slack(v, inc, state, free)
        return (slack < 0, slack, -int(v.severity), v.victim_id)   # saveable first, then least slack

    @staticmethod
    def _treatable(state: SimulationState, caps: set[Capability]) -> bool:
        return any(all(h.can_treat(c) for c in caps) for h in state.hospitals.values())

    # ───────── Ambulances ─────────
    def _ambulances(self, state: SimulationState) -> list[Decision]:
        out, free = [], list(state.available_ambulances())
        by_inc: dict[str, list[Victim]] = {}
        for v in state.waiting_victims():
            by_inc.setdefault(v.incident_id, []).append(v)
        while free and by_inc:
            iid, lead = min(((i, v) for i, vs in by_inc.items() for v in vs),
                            key=lambda p: self._priority(p[1], state.incidents[p[0]], state, free))
            inc = state.incidents[iid]
            amb = self._pick_ambulance(lead, inc, free)
            free.remove(amb)
            load, caps = [lead], {lead.required_capability}
            rest = sorted((v for v in by_inc[iid] if v.victim_id != lead.victim_id),
                          key=lambda v: self._priority(v, inc, state, free))
            for v in rest:
                if len(load) == amb.capacity:
                    break
                if self._treatable(state, caps | {v.required_capability}):
                    load.append(v)
                    caps.add(v.required_capability)
            taken = {v.victim_id for v in load}
            by_inc[iid] = [v for v in by_inc[iid] if v.victim_id not in taken]
            if not by_inc[iid]:
                del by_inc[iid]
            action = ProposedAction(action_type=ActionType.ASSIGN_AMBULANCE, ambulance_id=amb.ambulance_id,
                                    victim_ids=sorted(taken))
            out.append(Decision(action, iid, source=self.name))
        return out

    @staticmethod
    def _pick_ambulance(v: Victim, inc: Incident, free: list[Ambulance]) -> Ambulance:
        def dist(a: Ambulance) -> tuple:
            return (a.location.distance_to(inc.location), a.ambulance_id)
        best = min(free, key=dist)
        want = AmbulanceType.ALS if v.needs_als else AmbulanceType.BLS
        preferred = [a for a in free if a.ambulance_type == want and dist(a)[0] <= dist(best)[0] + ALS_TOLERANCE_KM]
        return min(preferred, key=dist) if preferred else best

    # ───────── Responder teams ─────────
    def _responders(self, state: SimulationState) -> list[Decision]:
        out, free = [], list(state.available_responders())
        free_amb = state.available_ambulances()
        covered = {(r.assigned_incident, r.responder_type) for r in state.responders.values() if r.assigned_incident}
        ranked = []
        for inc in state.visible_incidents():
            waiting = [v for v in inc.victims if v.status == VictimStatus.WAITING]
            if waiting:
                ranked.append((min(self._priority(v, inc, state, free_amb) for v in waiting), inc))
        ranked.sort(key=lambda p: p[0])
        for _, inc in ranked:
            needs = [inc.required_responder] if inc.required_responder else []
            uncovered_critical = any(v.is_critical and v.status == VictimStatus.WAITING
                                     and v.victim_id not in state.reservations for v in inc.victims)
            if uncovered_critical and ResponderType.MEDICAL not in needs:
                needs.append(ResponderType.MEDICAL)
            for kind in needs:
                if (inc.incident_id, kind) in covered:
                    continue
                team = min((r for r in free if r.responder_type == kind),
                           key=lambda r: (r.location.distance_to(inc.location), r.team_id), default=None)
                if team is not None:
                    free.remove(team)
                    covered.add((inc.incident_id, kind))
                    action = ProposedAction(action_type=ActionType.ASSIGN_RESPONDER, responder_id=team.team_id)
                    out.append(Decision(action, inc.incident_id, source=self.name))
        return out

    # ───────── Hospital admission ─────────
    def _admissions(self, state: SimulationState) -> list[Decision]:
        out, by_amb = [], {}
        for vid, aid in state.reservations.items():
            by_amb.setdefault(aid, []).append(vid)
        for aid, vids in sorted(by_amb.items()):
            victims = [state.find_victim(v) for v in vids]
            if any(v.status != VictimStatus.IN_TRANSPORT for v in victims) or any(v in state.admissions for v in vids):
                continue
            hospital_id = self._best_hospital(state, state.ambulances[aid], victims)
            if hospital_id is not None:
                action = ProposedAction(action_type=ActionType.ADMIT_PATIENT, hospital_id=hospital_id, victim_ids=vids)
                out.append(Decision(action, victims[0].incident_id, source=self.name))
        return out

    @staticmethod
    def _best_hospital(state: SimulationState, amb: Ambulance, victims: list[Victim]) -> str | None:
        caps = {v.required_capability for v in victims}
        capable = [h for h in state.hospitals.values() if all(h.can_treat(c) for c in caps)]

        def load(h) -> float:
            return (h.er_occupied + state.incoming_count(h.hospital_id) + len(victims)) / h.er_capacity

        pool = [h for h in capable if load(h) <= 1.0] or capable
        best = min(pool, key=lambda h: (amb.location.distance_to(h.location) + LOAD_PENALTY_KM * load(h),
                                        h.hospital_id), default=None)
        return best.hospital_id if best else None