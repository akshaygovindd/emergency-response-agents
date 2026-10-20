"""Scenario (fixed generated input) and SimulationState (the evolving world)."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator

from erc.config import ScenarioName
from erc.models.entities import (
    Ambulance, Hospital, Incident, ResponderTeam, StaffMember, StrictModel,
    Victim, VictimStatus,
)


class Scenario(StrictModel):
    """Output of the generator for one scenario type and one seed. Never mutated."""
    name: ScenarioName
    seed: int
    hospitals: list[Hospital] = Field(min_length=1)
    ambulances: list[Ambulance] = Field(min_length=1)
    responders: list[ResponderTeam]
    staff: list[StaffMember]
    incidents: list[Incident] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> Scenario:
        groups = {
            "hospital": [h.hospital_id for h in self.hospitals],
            "ambulance": [a.ambulance_id for a in self.ambulances],
            "responder": [r.team_id for r in self.responders],
            "staff": [s.staff_id for s in self.staff],
            "incident": [i.incident_id for i in self.incidents],
            "victim": [v.victim_id for i in self.incidents for v in i.victims],
        }
        for label, ids in groups.items():
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate {label} IDs")
        hospital_ids = set(groups["hospital"])
        for s in self.staff:
            if s.hospital_id not in hospital_ids:
                raise ValueError(f"{s.staff_id} assigned to unknown hospital {s.hospital_id}")
        return self

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.name.value}_seed{self.seed}.json"
        path.write_text(self.model_dump_json(indent=2))
        return path

    @classmethod
    def load(cls, path: Path) -> Scenario:
        return cls.model_validate_json(path.read_text())


class SimulationState(StrictModel):
    """The world at one moment. Owned and updated only by the simulator."""
    scenario_name: ScenarioName
    seed: int
    time_min: int = Field(default=0, ge=0)
    hospitals: dict[str, Hospital]
    ambulances: dict[str, Ambulance]
    responders: dict[str, ResponderTeam]
    staff: dict[str, StaffMember]
    incidents: dict[str, Incident]

    # Simulator bookkeeping: agents can read it through tools, never write it
    reservations: dict[str, str] = Field(default_factory=dict, description="victim_id -> ambulance_id")
    admissions: dict[str, str] = Field(default_factory=dict, description="victim_id -> hospital_id")
    first_contact_min: dict[str, int] = Field(default_factory=dict, description="victim_id -> minute")
    treatment_start_min: dict[str, int] = Field(default_factory=dict, description="victim_id -> minute")

    @classmethod
    def from_scenario(cls, scenario: Scenario) -> SimulationState:
        """Deep copy, so one run can never alter the scenario another run uses."""
        s = scenario.model_copy(deep=True)
        return cls(
            scenario_name=s.name, seed=s.seed,
            hospitals={h.hospital_id: h for h in s.hospitals},
            ambulances={a.ambulance_id: a for a in s.ambulances},
            responders={r.team_id: r for r in s.responders},
            staff={m.staff_id: m for m in s.staff},
            incidents={i.incident_id: i for i in s.incidents},
        )

    # ───────── Views (what anyone, including agents, may look at) ─────────
    def visible_incidents(self) -> list[Incident]:
        """Only incidents that have already arrived. Nobody sees the future."""
        return [i for i in self.incidents.values() if i.arrival_time_min <= self.time_min]

    def victims(self) -> list[Victim]:
        return [v for i in self.visible_incidents() for v in i.victims]

    def waiting_victims(self) -> list[Victim]:
        """Victims still waiting AND not yet reserved by any ambulance."""
        return [v for v in self.victims()
                if v.status == VictimStatus.WAITING and v.victim_id not in self.reservations]

    def find_victim(self, victim_id: str) -> Victim | None:
        return next((v for v in self.victims() if v.victim_id == victim_id), None)

    def available_ambulances(self) -> list[Ambulance]:
        return [a for a in self.ambulances.values() if a.is_available]

    def available_responders(self) -> list[ResponderTeam]:
        return [r for r in self.responders.values() if r.is_available]

    def incoming_count(self, hospital_id: str) -> int:
        """Victims admitted to this hospital who have not arrived there yet."""
        en_route = (VictimStatus.WAITING, VictimStatus.IN_TRANSPORT)
        return sum(
            1 for vid, hid in self.admissions.items()
            if hid == hospital_id and (v := self.find_victim(vid)) is not None and v.status in en_route
        )

    def summary(self) -> dict:
        """Compact snapshot for logs and the dashboard."""
        waiting = self.waiting_victims()
        open_statuses = (VictimStatus.WAITING, VictimStatus.IN_TRANSPORT)
        n_avail = len(self.available_ambulances())
        return {
            "time_min": self.time_min,
            "active_incidents": sum(
                any(v.status in open_statuses for v in i.victims) for i in self.visible_incidents()),
            "waiting_victims": len(waiting),
            "critical_waiting": sum(v.is_critical for v in waiting),
            "ambulances_available": n_avail,
            "ambulances_busy": len(self.ambulances) - n_avail,
            "responders_available": len(self.available_responders()),
            "staff_available": sum(m.is_available for m in self.staff.values()),
            "er_occupancy": {h.hospital_id: round(h.er_occupied / h.er_capacity, 2)
                             for h in self.hospitals.values()},
        }