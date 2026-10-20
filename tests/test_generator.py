"""Tests: generated scenarios must be reproducible and match their design."""
from statistics import mean

from erc.config import SCENARIOS, ScenarioName, seeds_for
from erc.models.entities import Capability
from erc.scenarios.generator import generate_all, generate_scenario


def test_same_seed_same_scenario():
    assert generate_scenario(ScenarioName.NORMAL, 42) == generate_scenario(ScenarioName.NORMAL, 42)


def test_different_seeds_differ():
    assert generate_scenario(ScenarioName.NORMAL, 42) != generate_scenario(ScenarioName.NORMAL, 43)


def test_incident_counts_match_config():
    for name, cfg in SCENARIOS.items():
        assert len(generate_scenario(name, 42).incidents) == cfg.n_incidents


def test_arrivals_sorted_and_in_window():
    for name, cfg in SCENARIOS.items():
        times = [i.arrival_time_min for i in generate_scenario(name, 42).incidents]
        assert times == sorted(times)
        assert max(times) < cfg.arrival_window_min


def test_bottleneck_is_constrained():
    s = generate_scenario(ScenarioName.BOTTLENECK, 42)
    assert len(s.ambulances) == 2
    trauma = next(h for h in s.hospitals if h.hospital_id == "H-T")
    assert trauma.treatment_occupied[Capability.TRAUMA] > 0


def test_bottleneck_more_severe_than_normal():
    def avg_severity(name):
        return mean(v.severity for seed in seeds_for(name)
                    for i in generate_scenario(name, seed).incidents for v in i.victims)
    assert avg_severity(ScenarioName.BOTTLENECK) > avg_severity(ScenarioName.NORMAL)


def test_critical_victims_need_als():
    s = generate_scenario(ScenarioName.SURGE, 42)
    for v in (v for i in s.incidents for v in i.victims):
        assert v.needs_als == v.is_critical


def test_generate_all_writes_every_scenario(tmp_path):
    paths = generate_all(tmp_path)
    assert len(paths) == sum(cfg.n_seeds for cfg in SCENARIOS.values())