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




def test_coordination_and_cost_metrics(tiny_scenario):
    e = Engine(tiny_scenario, NaivePolicy())
    e.run()
    log = e.log
    log.record(5, "conflict_detected", conflict_id="C1", conflict_type="resource", proposal_ids=["P1", "P2"])
    log.record(5, "conflict_resolved", conflict_id="C1", method="negotiation", winners=["P1", "P3"], losers=["P2"])
    log.record(5, "proposal_invalid", agent="dispatch", tool="x", args={}, reason="unknown_resource", detail="")
    log.record(5, "llm_call", agent="dispatch", tokens_in=1_000_000, tokens_out=0, latency_s=1.0,
               cache_hit=False, requests=2)
    log.record(6, "llm_call", agent="dispatch", tokens_in=0, tokens_out=1_000_000, latency_s=1.0,
               cache_hit=True, requests=1)
    m = compute_metrics(e.state, log, "test")
    assert (m.conflicts, m.resolved_by_negotiation, m.counters_accepted, m.invalid_proposals) == (1, 1, 1, 1)
    assert m.cache_hits == 1 and m.fresh_tokens == 1_000_000 and m.model_requests == 3
    assert m.est_cost_usd == pytest.approx(0.75 + 4.50)