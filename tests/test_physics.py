"""Tests: travel and deterioration must be fair, bounded, and correct."""
from erc.config import SETTINGS
from erc.models.entities import Capability, Location, Severity, Victim, VictimStatus
from erc.sim.deterioration import deteriorate, is_deteriorated
from erc.sim.travel import travel_time_min


def critical_victim(deadline=10):
    return Victim(victim_id="V-1", incident_id="INC-1", severity=Severity.CRITICAL,
                  required_capability=Capability.TRAUMA, needs_als=True, deadline_min=deadline)


A, B = Location(x=0, y=0), Location(x=6, y=4)   # 10 km apart


def test_travel_is_reproducible():
    assert travel_time_min(42, A, B, 20) == travel_time_min(42, A, B, 20)


def test_travel_within_traffic_bounds():
    # 10 km at 1 km/min, traffic factor 0.8 to 1.5 -> 8 to 15 minutes
    for t in range(0, 90, 5):
        assert 8 <= travel_time_min(42, A, B, t) <= 15


def test_no_travel_needed():
    assert travel_time_min(42, A, A, 0) == 0


def test_hits_critical_exactly_at_deadline_without_care():
    v = critical_victim(deadline=10)
    for _ in range(10):
        deteriorate(v)
    assert not is_deteriorated(v)
    deteriorate(v)
    assert is_deteriorated(v)


def test_crew_care_slows_decline():
    d = SETTINGS.deterioration
    none, bls, als = critical_victim(), critical_victim(), critical_victim()
    deteriorate(none, minutes=5)
    deteriorate(bls, minutes=5, care_factor=d.bls_care_factor)
    deteriorate(als, minutes=5, care_factor=d.als_care_factor)
    assert als.condition > bls.condition > none.condition


def test_no_decline_during_treatment():
    v = critical_victim()
    v.status = VictimStatus.IN_TREATMENT
    deteriorate(v, minutes=30)
    assert v.condition == 100