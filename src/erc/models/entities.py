"""Core entities of the synthetic emergency environment.

Every physical "thing" in the simulation is a Pydantic model. These models are
the single source of truth: the simulator updates them, the validator checks
them, and agents only ever see read-only views of them.
"""
from __future__ import annotations

from enum import Enum, IntEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

GRID_SIZE_KM = 20.0


class StrictModel(BaseModel):
    """Rejects unknown fields and re-validates whenever a field changes."""
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ───────────────────────── Enums ─────────────────────────
class Capability(str, Enum):
    TRAUMA = "trauma"
    BURN = "burn"
    GENERAL = "general"


class IncidentType(str, Enum):
    VEHICLE_COLLISION = "vehicle_collision"
    BUILDING_FIRE = "building_fire"
    STRUCTURAL_COLLAPSE = "structural_collapse"
    INDUSTRIAL_ACCIDENT = "industrial_accident"
    MEDICAL_EMERGENCY = "medical_emergency"


class Severity(IntEnum):
    MINOR = 1
    MODERATE = 2
    SERIOUS = 3
    SEVERE = 4
    CRITICAL = 5


class VictimStatus(str, Enum):
    WAITING = "waiting"
    IN_TRANSPORT = "in_transport"
    IN_TREATMENT = "in_treatment"
    TREATED = "treated"
    UNSERVED = "unserved"


class AmbulanceType(str, Enum):
    BLS = "basic_life_support"
    ALS = "advanced_life_support"


class UnitStatus(str, Enum):
    AVAILABLE = "available"
    EN_ROUTE = "en_route"
    ON_SCENE = "on_scene"
    TRANSPORTING = "transporting"
    RETURNING = "returning"


class ResponderType(str, Enum):
    FIRE = "fire"
    RESCUE = "rescue"
    MEDICAL = "medical"


class StaffRole(str, Enum):
    DOCTOR = "doctor"
    NURSE = "nurse"


class SkillLevel(IntEnum):
    NONE = 0
    BASIC = 1
    INTERMEDIATE = 2
    EXPERT = 3


# ───────────────────────── Location ─────────────────────────
class Location(StrictModel):
    x: float = Field(ge=0, le=GRID_SIZE_KM, description="km east")
    y: float = Field(ge=0, le=GRID_SIZE_KM, description="km north")

    def distance_to(self, other: Location) -> float:
        """Manhattan distance in km (grid streets, no diagonals)."""
        return abs(self.x - other.x) + abs(self.y - other.y)


# ───────────────────── Victims and incidents ─────────────────────
class Victim(StrictModel):
    victim_id: str
    incident_id: str
    severity: Severity
    required_capability: Capability
    needs_als: bool = Field(description="Needs an advanced life support ambulance")
    deadline_min: int = Field(gt=0, description="Minutes after arrival before condition turns critical")
    condition: float = Field(default=100.0, ge=0, le=100, description="Synthetic score, 100 = stable")
    status: VictimStatus = VictimStatus.WAITING

    @property
    def is_critical(self) -> bool:
        return self.severity >= Severity.SEVERE


class Incident(StrictModel):
    incident_id: str
    incident_type: IncidentType
    location: Location
    arrival_time_min: int = Field(ge=0)
    victims: list[Victim] = Field(min_length=1)
    required_responder: ResponderType | None = None
    description: str | None = Field(default=None, description="LLM-written report, added later")

    @model_validator(mode="after")
    def _victims_belong_here(self) -> Incident:
        for v in self.victims:
            if v.incident_id != self.incident_id:
                raise ValueError(f"{v.victim_id} belongs to {v.incident_id}, not {self.incident_id}")
        return self

    @property
    def victim_count(self) -> int:
        return len(self.victims)

    @property
    def max_severity(self) -> Severity:
        return max(v.severity for v in self.victims)

    @property
    def critical_victim_count(self) -> int:
        return sum(v.is_critical for v in self.victims)


# ───────────────────────── Hospitals and staff ─────────────────────────
class Hospital(StrictModel):
    hospital_id: str
    name: str
    location: Location
    er_capacity: int = Field(gt=0, description="Patients waiting for evaluation")
    treatment_slots: dict[Capability, int] = Field(description="Concurrent patients per treatment type")
    beds: int = Field(gt=0)
    er_occupied: int = Field(default=0, ge=0)
    treatment_occupied: dict[Capability, int] = Field(default_factory=dict)
    beds_occupied: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _within_capacity(self) -> Hospital:
        if self.er_occupied > self.er_capacity:
            raise ValueError(f"{self.hospital_id}: ER over capacity")
        if self.beds_occupied > self.beds:
            raise ValueError(f"{self.hospital_id}: beds over capacity")
        for cap, used in self.treatment_occupied.items():
            if used < 0 or used > self.treatment_slots.get(cap, 0):
                raise ValueError(f"{self.hospital_id}: {cap.value} slots over capacity")
        return self

    def can_treat(self, capability: Capability) -> bool:
        return self.treatment_slots.get(capability, 0) > 0

    def free_slots(self, capability: Capability) -> int:
        return self.treatment_slots.get(capability, 0) - self.treatment_occupied.get(capability, 0)


class StaffMember(StrictModel):
    staff_id: str
    role: StaffRole
    hospital_id: str
    skills: dict[Capability, SkillLevel]
    max_patients: int = Field(gt=0, description="Workload limit")
    current_patients: int = Field(default=0, ge=0)
    on_shift: bool = True

    @model_validator(mode="after")
    def _within_workload(self) -> StaffMember:
        if self.current_patients > self.max_patients:
            raise ValueError(f"{self.staff_id}: workload limit exceeded")
        return self

    @property
    def is_available(self) -> bool:
        return self.on_shift and self.current_patients < self.max_patients

    def is_qualified(self, capability: Capability, minimum: SkillLevel = SkillLevel.INTERMEDIATE) -> bool:
        return self.skills.get(capability, SkillLevel.NONE) >= minimum


# ───────────────────── Ambulances and responders ─────────────────────
class Ambulance(StrictModel):
    ambulance_id: str
    ambulance_type: AmbulanceType
    capacity: int = Field(default=2, gt=0)
    location: Location
    base_location: Location
    status: UnitStatus = UnitStatus.AVAILABLE
    assigned_incident: str | None = None
    victims_onboard: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Ambulance:
        if len(self.victims_onboard) > self.capacity:
            raise ValueError(f"{self.ambulance_id}: over capacity")
        if self.status == UnitStatus.AVAILABLE and self.assigned_incident is not None:
            raise ValueError(f"{self.ambulance_id}: available but still assigned")
        return self

    @property
    def is_available(self) -> bool:
        return self.status == UnitStatus.AVAILABLE


class ResponderTeam(StrictModel):
    team_id: str
    responder_type: ResponderType
    location: Location
    base_location: Location
    status: UnitStatus = UnitStatus.AVAILABLE
    assigned_incident: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ResponderTeam:
        if self.status == UnitStatus.AVAILABLE and self.assigned_incident is not None:
            raise ValueError(f"{self.team_id}: available but still assigned")
        return self

    @property
    def is_available(self) -> bool:
        return self.status == UnitStatus.AVAILABLE