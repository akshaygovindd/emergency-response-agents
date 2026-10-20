"""Tests: the greedy baseline must make the smart choices it claims to make."""
from erc.models.entities import Location, UnitStatus, VictimStatus
from erc.models.messages import ActionType
from erc.models.state import SimulationState
from erc.policies.greedy import GreedyPolicy
from erc.policies.naive import NaivePolicy
from erc.sim.engine import Engine


def first_ambulance_decision(policy, state):
    return next(d for d in policy.decide(state) if d.action.action_type == ActionType.ASSIGN_AMBULANCE)


def test_greedy_gets_critical_victim_treated(tiny_scenario):
    e = Engine(tiny_scenario, GreedyPolicy())
    e.run()
    assert e.state.find_victim("V-01").status == VictimStatus.TREATED


def test_greedy_sends_als_to_critical_victim(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    state.ambulances["AMB-02"].location = Location(x=6, y=5)   # BLS now closest
    assert first_ambulance_decision(NaivePolicy(), state).action.ambulance_id == "AMB-02"
    assert first_ambulance_decision(GreedyPolicy(), state).action.ambulance_id == "AMB-01"


def test_greedy_helps_the_saveable_first(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    state.time_min = 10                                      # V-01 is past saving, V-02 is not
    state.ambulances["AMB-01"].status = UnitStatus.EN_ROUTE   # only one ambulance free
    assert first_ambulance_decision(NaivePolicy(), state).incident_id == "INC-01"
    assert first_ambulance_decision(GreedyPolicy(), state).incident_id == "INC-02"


def test_greedy_avoids_full_er(tiny_scenario):
    state = SimulationState.from_scenario(tiny_scenario)
    state.time_min = 10
    state.reservations["V-02"] = "AMB-02"
    state.find_victim("V-02").status = VictimStatus.IN_TRANSPORT
    state.hospitals["H-T"].er_occupied = 4                    # Trauma Center ER full
    decisions = GreedyPolicy()._admissions(state)
    assert decisions[0].action.hospital_id == "H-G"