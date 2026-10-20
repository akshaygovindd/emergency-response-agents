"""Shared test fixtures: a tiny, hand-built scenario."""
import pytest

from erc.config import ScenarioName
from erc.models.entities import (
    Ambulance, AmbulanceType, Capability, Hospital, Incident, IncidentType, Location,
    ResponderTeam, ResponderType, Severity, SkillLevel, StaffMember, StaffRole, Victim,
)
from erc.models.state import Scenario


def loc(x, y):
    return Location(x=x, y=y)


def victim(vid, iid, sev, cap):
    return Victim(victim_id=vid, incident_id=iid, severity=sev, required_capability=cap,
                  needs_als=sev >= Severity.SEVERE, deadline_min=10)


@pytest.fixture
def tiny_scenario() -> Scenario:
    hospitals = [
        Hospital(hospital_id="H-T", name="Trauma Center", location=loc(5, 5), er_capacity=4,
                 treatment_slots={Capability.TRAUMA: 2, Capability.GENERAL: 1}, beds=6),
        Hospital(hospital_id="H-G", name="General Hospital", location=loc(15, 15), er_capacity=6,
                 treatment_slots={Capability.GENERAL: 3}, beds=10),
    ]
    ambulances = [
        Ambulance(ambulance_id="AMB-01", ambulance_type=AmbulanceType.ALS,
                  location=loc(4, 4), base_location=loc(4, 4)),
        Ambulance(ambulance_id="AMB-02", ambulance_type=AmbulanceType.BLS,
                  location=loc(14, 14), base_location=loc(14, 14)),
    ]
    responders = [ResponderTeam(team_id="FIRE-1", responder_type=ResponderType.FIRE,
                                location=loc(10, 10), base_location=loc(10, 10))]
    staff = [StaffMember(staff_id="D-01", role=StaffRole.DOCTOR, hospital_id="H-T",
                         skills={Capability.TRAUMA: SkillLevel.EXPERT}, max_patients=2)]
    incidents = [
        Incident(incident_id="INC-01", incident_type=IncidentType.VEHICLE_COLLISION,
                 location=loc(6, 6), arrival_time_min=0,
                 victims=[victim("V-01", "INC-01", Severity.CRITICAL, Capability.TRAUMA)]),
        Incident(incident_id="INC-02", incident_type=IncidentType.BUILDING_FIRE,
                 location=loc(12, 8), arrival_time_min=10, required_responder=ResponderType.FIRE,
                 victims=[victim("V-02", "INC-02", Severity.SERIOUS, Capability.GENERAL)]),
    ]
    return Scenario(name=ScenarioName.NORMAL, seed=42, hospitals=hospitals, ambulances=ambulances,
                    responders=responders, staff=staff, incidents=incidents)