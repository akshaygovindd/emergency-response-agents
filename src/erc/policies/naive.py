"""Baseline 1 (naive): first come, first served; nearest everything.

Ignores severity, deadlines, ambulance type, and hospital load. Represents a
dispatcher with no prioritisation at all.
"""
from __future__ import annotations

from erc.models.messages import ActionType, ProposedAction
from erc.models.entities import VictimStatus
from erc.models.state import SimulationState
from erc.sim.engine import Decision


class NaivePolicy:
    name = "naive"

    def decide(self, state: SimulationState) -> list[Decision]:
        return self._ambulances(state) + self._responders(state) + self._admissions(state)

    @staticmethod
    def _incidents_in_arrival_order(state: SimulationState):
        return sorted(state.visible_incidents(), key=lambda i: (i.arrival_time_min, i.incident_id))

    def _ambulances(self, state: SimulationState) -> list[Decision]:
        out, free, waiting = [], list(state.available_ambulances()), state.waiting_victims()
        for inc in self._incidents_in_arrival_order(state):
            victims = [v for v in waiting if v.incident_id == inc.incident_id]
            while victims and free:
                amb = min(free, key=lambda a: (a.location.distance_to(inc.location), a.ambulance_id))
                free.remove(amb)
                load, victims = victims[:amb.capacity], victims[amb.capacity:]
                action = ProposedAction(action_type=ActionType.ASSIGN_AMBULANCE, ambulance_id=amb.ambulance_id,
                                        victim_ids=[v.victim_id for v in load])
                out.append(Decision(action, inc.incident_id, source=self.name))
        return out

    def _responders(self, state: SimulationState) -> list[Decision]:
        out, free = [], list(state.available_responders())
        covered = {r.assigned_incident for r in state.responders.values() if r.assigned_incident}
        for inc in self._incidents_in_arrival_order(state):
            if inc.required_responder is None or inc.incident_id in covered:
                continue
            if not any(v.status == VictimStatus.WAITING for v in inc.victims):
                continue
            team = min((r for r in free if r.responder_type == inc.required_responder),
                       key=lambda r: (r.location.distance_to(inc.location), r.team_id), default=None)
            if team is not None:
                free.remove(team)
                action = ProposedAction(action_type=ActionType.ASSIGN_RESPONDER, responder_id=team.team_id)
                out.append(Decision(action, inc.incident_id, source=self.name))
        return out

    def _admissions(self, state: SimulationState) -> list[Decision]:
        out, by_ambulance = [], {}
        for vid, aid in state.reservations.items():
            by_ambulance.setdefault(aid, []).append(vid)
        for aid, vids in sorted(by_ambulance.items()):
            victims = [state.find_victim(v) for v in vids]
            if any(v.status != VictimStatus.IN_TRANSPORT for v in victims) or any(v in state.admissions for v in vids):
                continue
            caps = {v.required_capability for v in victims}
            options = [h for h in state.hospitals.values() if all(h.can_treat(c) for c in caps)]
            if not options:
                continue
            amb = state.ambulances[aid]
            h = min(options, key=lambda h: (h.location.distance_to(amb.location), h.hospital_id))
            action = ProposedAction(action_type=ActionType.ADMIT_PATIENT, hospital_id=h.hospital_id, victim_ids=vids)
            out.append(Decision(action, victims[0].incident_id, source=self.name))
        return out