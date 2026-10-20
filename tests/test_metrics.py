"""Tests: metrics and statistics must be correct and honest."""
import pytest

from erc.eval.metrics import compute_metrics
from erc.eval.stats import paired_comparison, summarize, t_critical
from erc.models.messages import ActionType, ProposedAction
from erc.policies.naive import NaivePolicy
from erc.sim.engine import Decision, Engine


class BrokenPolicy:
    name = "broken"

    def decide(self, state):
        action = ProposedAction(action_type=ActionType.ASSIGN_AMBULANCE, ambulance_id="AMB-99",
                                victim_ids=["V-01"])
        return [Decision(action, "INC-01", source=self.name)]


def metrics_for(scenario, policy):
    e = Engine(scenario, policy)
    e.run()
    return compute_metrics(e.state, e.log, policy.name)


def test_naive_reaches_critical_victim_in_time(tiny_scenario):
    m = metrics_for(tiny_scenario, NaivePolicy())
    assert (m.n_victims, m.n_critical) == (2, 1)
    assert m.critical_service_rate == 1.0
    assert m.critical_unserved == 0
    assert m.actions_rejected == 0
    assert m.response_mean is not None


def test_broken_policy_is_measured_as_broken(tiny_scenario):
    m = metrics_for(tiny_scenario, BrokenPolicy())
    assert m.critical_service_rate == 0.0
    assert m.critical_unserved == 1
    assert m.rejection_reasons["unknown_resource"] >= 1


def test_condition_at_contact_is_exact(tiny_scenario):
    m = metrics_for(tiny_scenario, NaivePolicy())
    # V-01: deadline 10 -> loses 6 points per minute until first contact
    assert m.mean_critical_condition_at_contact == pytest.approx(100 - 6 * m.critical_response_mean)


def test_utilization_is_a_fraction(tiny_scenario):
    m = metrics_for(tiny_scenario, NaivePolicy())
    assert 0 < m.ambulance_utilization < 1
    assert 0 <= m.responder_utilization < 1


def test_summarize():
    s = summarize([1, 2, 3, 4, 5])
    assert (s.mean, s.median) == (3, 3)
    assert s.std == pytest.approx(1.5811, abs=1e-3)
    assert s.ci_low < 3 < s.ci_high


def test_summarize_ignores_missing_values():
    assert summarize([None, None]).n == 0
    assert summarize([None, 4.0]).mean == 4.0


def test_paired_comparison():
    same = paired_comparison([0.5, 0.6, 0.7], [0.5, 0.6, 0.7])
    assert same.mean_diff == 0 and same.ties == 3 and not same.significant
    better = paired_comparison([0.9, 0.8, 0.95, 0.85], [0.5, 0.45, 0.6, 0.5])
    assert better.wins == 4 and better.significant


def test_t_critical_is_conservative():
    assert t_critical(9) == 2.262
    assert t_critical(11) == 2.228     # uses df=10, slightly wider interval
    assert t_critical(100) == 1.96