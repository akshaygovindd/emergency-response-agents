"""Tests: the validator must accept possible actions and reject impossible ones."""
from erc.models.entities import UnitStatus
from erc.models.messages import ActionType, ProposedAction, RejectionReason
from erc.models.state import SimulationState
from erc.sim.validator import validate

R = RejectionReason


def amb(ambulance_id="AMB-01", victims=("V-01",)):
    return ProposedAction(action_type=ActionType.ASSIGN_AMBULANCE,
                          ambulance_id=ambulance_id, victim_ids=list(victims))


def admit(hospital_id, victims=("V-01",)):
    return ProposedAction(action_type=ActionType.ADMIT_PATIENT,
                          hospital_id=hospital_id, victim_ids=list(victims))


def test_valid_ambulance_assignment(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    assert validate(amb(), "INC-01", state).accepted


def test_unknown_ambulance(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    assert validate(amb("AMB-99"), "INC-01", state).reason == R.UNKNOWN_RESOURCE


def test_future_incident(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)   # INC-02 arrives at minute 10
    assert validate(amb(victims=("V-02",)), "INC-02", state).reason == R.INCIDENT_NOT_ACTIVE


def test_busy_ambulance(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    state.ambulances["AMB-01"].status = UnitStatus.EN_ROUTE
    assert validate(amb(), "INC-01", state).reason == R.AMBULANCE_UNAVAILABLE


def test_over_capacity(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    assert validate(amb(victims=("V-01", "V-x", "V-y")), "INC-01", state).reason == R.AMBULANCE_OVER_CAPACITY


def test_victim_already_reserved(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    state.reservations["V-01"] = "AMB-02"
    assert validate(amb(), "INC-01", state).reason == R.VICTIM_UNAVAILABLE


def test_admission_requires_pickup_first(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    assert validate(admit("H-T"), "INC-01", state).reason == R.VICTIM_UNAVAILABLE


def test_hospital_without_capability(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    state.reservations["V-01"] = "AMB-01"
    assert validate(admit("H-G"), "INC-01", state).reason == R.HOSPITAL_LACKS_CAPABILITY


def test_full_er(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    state.reservations["V-01"] = "AMB-01"
    state.hospitals["H-T"].er_occupied = 4
    assert validate(admit("H-T"), "INC-01", state).reason == R.HOSPITAL_FULL


def test_valid_admission(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    state.reservations["V-01"] = "AMB-01"
    assert validate(admit("H-T"), "INC-01", state).accepted


def test_validator_never_changes_state(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    before = state.model_dump()
    validate(amb(), "INC-01", state)
    validate(admit("H-T"), "INC-01", state)
    assert state.model_dump() == before