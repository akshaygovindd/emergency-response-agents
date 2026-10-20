"""Metrics: everything measured about one run, computed from its final state and event log.

Primary metric (fixed before any agent run):
    critical_service_rate = share of critical victims (severity 4-5) whose first
    medical contact happened within their deadline, measured from incident arrival.
"""
from __future__ import annotations

from collections import Counter

import numpy as np
from pydantic import BaseModel

from erc.logging.event_log import EventLog
from erc.models.entities import Victim, VictimStatus
from erc.models.state import SimulationState
from erc.sim.deterioration import loss_rate

HOSPITALIZED = {VictimStatus.AWAITING_TREATMENT, VictimStatus.IN_TREATMENT, VictimStatus.TREATED}
TREATMENT_STARTED = {VictimStatus.IN_TREATMENT, VictimStatus.TREATED}


class RunMetrics(BaseModel):
    run_id: str
    scenario: str
    seed: int
    mode: str
    # Outcomes
    n_victims: int
    n_critical: int
    critical_service_rate: float | None          # PRIMARY
    critical_unserved: int                       # critical victims never reached
    contacted_rate: float
    hospitalized_rate: float
    treatment_started_rate: float
    service_rate_by_severity: dict[int, float]
    mean_critical_condition_at_contact: float | None
    deteriorated: int
    # Speed (minutes from incident arrival to first medical contact)
    response_mean: float | None
    response_median: float | None
    response_p95: float | None
    critical_response_mean: float | None
    # Efficiency
    ambulance_utilization: float
    responder_utilization: float
    er_full_events: int
    # Coordination and reliability
    policy_calls: int
    actions_accepted: int
    actions_rejected: int
    rejection_reasons: dict[str, int]
    agent_messages: int = 0
    negotiations: int = 0
    counter_proposals: int = 0
    mean_negotiation_rounds: float | None = None
    # Cost (zero for baselines)
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    llm_latency_s: float = 0.0


def _maybe(values: list[float], fn) -> float | None:
    return float(fn(values)) if values else None


def compute_metrics(state: SimulationState, log: EventLog, mode: str) -> RunMetrics:
    victims = state.victims()
    arrival = {i.incident_id: i.arrival_time_min for i in state.incidents.values()}

    def response(v: Victim) -> int | None:
        contact = state.first_contact_min.get(v.victim_id)
        return None if contact is None else contact - arrival[v.incident_id]

    def in_time(v: Victim) -> bool:
        r = response(v)
        return r is not None and r <= v.deadline_min

    critical = [v for v in victims if v.is_critical]
    responses = [r for v in victims if (r := response(v)) is not None]
    critical_responses = [r for v in critical if (r := response(v)) is not None]

    by_severity = {}
    for sev in range(1, 6):
        group = [v for v in victims if int(v.severity) == sev]
        if group:
            by_severity[sev] = sum(in_time(v) for v in group) / len(group)

    # Exact: before first contact a victim receives no care, so decline is linear
    condition_at_contact = [max(0.0, 100.0 - loss_rate(v) * response(v))
                            for v in critical if response(v) is not None]

    snaps = log.of_kind("snapshot")
    n_amb, n_resp = len(state.ambulances), len(state.responders)
    amb_util = float(np.mean([s["ambulances_busy"] / n_amb for s in snaps])) if snaps and n_amb else 0.0
    resp_util = (float(np.mean([(n_resp - s["responders_available"]) / n_resp for s in snaps]))
                 if snaps and n_resp else 0.0)
    er_full_events, was_full = 0, {}
    for s in snaps:
        for hid, occupancy in s["er_occupancy"].items():
            full = occupancy >= 1.0
            if full and not was_full.get(hid, False):
                er_full_events += 1
            was_full[hid] = full

    rejected = log.of_kind("action_rejected")
    messages = log.of_kind("agent_message")
    rounds: dict[str, int] = {}
    for m in messages:
        if m.get("negotiation_id"):
            rounds[m["negotiation_id"]] = max(rounds.get(m["negotiation_id"], 0), m.get("round", 0))
    llm = log.of_kind("llm_call")
    finished = log.of_kind("run_finished")

    return RunMetrics(
        run_id=log.run_id, scenario=state.scenario_name.value, seed=state.seed, mode=mode,
        n_victims=len(victims), n_critical=len(critical),
        critical_service_rate=(sum(in_time(v) for v in critical) / len(critical)) if critical else None,
        critical_unserved=sum(response(v) is None for v in critical),
        contacted_rate=len(responses) / len(victims) if victims else 0.0,
        hospitalized_rate=sum(v.status in HOSPITALIZED for v in victims) / len(victims) if victims else 0.0,
        treatment_started_rate=(sum(v.status in TREATMENT_STARTED for v in victims) / len(victims)
                                if victims else 0.0),
        service_rate_by_severity=by_severity,
        mean_critical_condition_at_contact=_maybe(condition_at_contact, np.mean),
        deteriorated=len(log.of_kind("victim_deteriorated")),
        response_mean=_maybe(responses, np.mean),
        response_median=_maybe(responses, np.median),
        response_p95=_maybe(responses, lambda x: np.percentile(x, 95)),
        critical_response_mean=_maybe(critical_responses, np.mean),
        ambulance_utilization=amb_util,
        responder_utilization=resp_util,
        er_full_events=er_full_events,
        policy_calls=finished[-1]["policy_calls"] if finished else 0,
        actions_accepted=len(log.of_kind("action_accepted")),
        actions_rejected=len(rejected),
        rejection_reasons=dict(Counter(e["reason"] for e in rejected)),
        agent_messages=len(messages),
        negotiations=len(rounds),
        counter_proposals=sum(m.get("message_type") == "counter_proposal" for m in messages),
        mean_negotiation_rounds=_maybe(list(rounds.values()), np.mean),
        llm_calls=len(llm),
        tokens_in=sum(e.get("tokens_in", 0) for e in llm),
        tokens_out=sum(e.get("tokens_out", 0) for e in llm),
        llm_latency_s=float(sum(e.get("latency_s", 0.0) for e in llm)),
    )