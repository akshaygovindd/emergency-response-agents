"""Tests: configuration must be internally consistent."""
from erc.config import BASE_SEED, SCENARIOS, SETTINGS, ScenarioName, seeds_for


def test_severity_weights_sum_to_one():
    for cfg in SCENARIOS.values():
        assert abs(sum(cfg.severity_weights) - 1.0) < 1e-9, cfg.name


def test_seeds_are_deterministic():
    assert seeds_for(ScenarioName.NORMAL) == seeds_for(ScenarioName.NORMAL)
    assert seeds_for(ScenarioName.NORMAL)[0] == BASE_SEED
    assert len(seeds_for(ScenarioName.SURGE, oracle=True)) == 3


def test_bottleneck_leaves_ambulances():
    cfg = SCENARIOS[ScenarioName.BOTTLENECK]
    assert 0 < SETTINGS.env.n_ambulances - cfg.ambulances_out_of_service


def test_deadlines_tighter_for_higher_severity():
    d = SETTINGS.deterioration.deadline_range_min
    for sev in range(1, 5):
        assert d[sev + 1][1] <= d[sev][1]