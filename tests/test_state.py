"""Tests: scenarios must be consistent, and state must protect fairness."""
import pytest
from pydantic import ValidationError

from erc.models.entities import UnitStatus
from erc.models.state import Scenario, SimulationState


def test_duplicate_ids_rejected(tiny_scenario):
    data = tiny_scenario.model_dump()
    data["ambulances"].append(data["ambulances"][0])
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)


def test_staff_must_belong_to_known_hospital(tiny_scenario):
    data = tiny_scenario.model_dump()
    data["staff"][0]["hospital_id"] = "H-NOPE"
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)


def test_nobody_sees_future_incidents(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    assert [i.incident_id for i in state.visible_incidents()] == ["INC-01"]
    state.time_min = 10
    assert len(state.visible_incidents()) == 2


def test_runs_cannot_change_the_scenario(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    state.ambulances["AMB-01"].status = UnitStatus.EN_ROUTE
    state.ambulances["AMB-01"].assigned_incident = "INC-01"
    assert tiny_scenario.ambulances[0].status == UnitStatus.AVAILABLE


def test_save_and_load_roundtrip(tiny_scenario, tmp_path):
    path = tiny_scenario.save(tmp_path)
    assert Scenario.load(path) == tiny_scenario


def test_summary_counts(tiny_scenario):
    s = SimulationState.from_scenario(tiny_scenario).summary()
    assert s["active_incidents"] == 1
    assert s["critical_waiting"] == 1
    assert s["ambulances_available"] == 2