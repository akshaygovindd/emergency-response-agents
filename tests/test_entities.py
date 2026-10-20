"""Tests: the entity models must reject every impossible state."""
import pytest
from pydantic import ValidationError

from erc.models.entities import (
    Ambulance, AmbulanceType, Capability, Hospital, Incident, IncidentType,
    Location, Severity, SkillLevel, StaffMember, StaffRole, Victim,
)


def make_victim(incident_id="INC-01", severity=Severity.CRITICAL):
    return Victim(victim_id="V-01", incident_id=incident_id, severity=severity,
                  required_capability=Capability.TRAUMA, needs_als=True, deadline_min=8)


def make_hospital():
    return Hospital(hospital_id="H-T", name="Trauma Center", location=Location(x=5, y=5),
                    er_capacity=6, treatment_slots={Capability.TRAUMA: 2}, beds=10)


def make_ambulance():
    loc = Location(x=1, y=1)
    return Ambulance(ambulance_id="AMB-01", ambulance_type=AmbulanceType.ALS,
                     location=loc, base_location=loc)


def test_valid_incident_properties():
    inc = Incident(incident_id="INC-01", incident_type=IncidentType.VEHICLE_COLLISION,
                   location=Location(x=3, y=4), arrival_time_min=0, victims=[make_victim()])
    assert inc.victim_count == 1
    assert inc.max_severity == Severity.CRITICAL
    assert inc.critical_victim_count == 1


def test_manhattan_distance():
    assert Location(x=0, y=0).distance_to(Location(x=3, y=4)) == 7


def test_location_off_map_rejected():
    with pytest.raises(ValidationError):
        Location(x=25, y=5)


def test_victim_from_other_incident_rejected():
    with pytest.raises(ValidationError):
        Incident(incident_id="INC-01", incident_type=IncidentType.BUILDING_FIRE,
                 location=Location(x=1, y=1), arrival_time_min=0,
                 victims=[make_victim(incident_id="INC-99")])


def test_incident_without_victims_rejected():
    with pytest.raises(ValidationError):
        Incident(incident_id="INC-01", incident_type=IncidentType.BUILDING_FIRE,
                 location=Location(x=1, y=1), arrival_time_min=0, victims=[])


def test_hospital_er_overload_rejected():
    h = make_hospital()
    with pytest.raises(ValidationError):
        h.er_occupied = 7


def test_hospital_treatment_overload_rejected():
    h = make_hospital()
    with pytest.raises(ValidationError):
        h.treatment_occupied = {Capability.TRAUMA: 3}


def test_ambulance_over_capacity_rejected():
    a = make_ambulance()
    with pytest.raises(ValidationError):
        a.victims_onboard = ["V-1", "V-2", "V-3"]


def test_available_ambulance_cannot_be_assigned():
    a = make_ambulance()
    with pytest.raises(ValidationError):
        a.assigned_incident = "INC-01"


def test_staff_workload_limit_rejected():
    s = StaffMember(staff_id="D-01", role=StaffRole.DOCTOR, hospital_id="H-T",
                    skills={Capability.TRAUMA: SkillLevel.EXPERT}, max_patients=2)
    with pytest.raises(ValidationError):
        s.current_patients = 3


def test_staff_qualification():
    s = StaffMember(staff_id="N-01", role=StaffRole.NURSE, hospital_id="H-T",
                    skills={Capability.BURN: SkillLevel.BASIC}, max_patients=3)
    assert not s.is_qualified(Capability.BURN)
    assert not s.is_qualified(Capability.TRAUMA)
