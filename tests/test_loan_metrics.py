"""Tests: v3 metrics (pre-registered treatment-wait metrics and loan counters) from synthetic logs."""
import pytest

from erc.eval.metrics import compute_metrics, treatment_wait_metrics
from erc.logging.event_log import EventLog
from erc.models.entities import Severity
from erc.models.state import SimulationState


def state_with(tiny_scenario, extra_critical=0):
    sc = tiny_scenario.model_copy(deep=True)
    from conftest import victim
    from erc.models.entities import Capability
    for i in range(extra_critical):
        sc.incidents[0].victims.append(victim(f"V-0{i + 3}", "INC-01", Severity.SEVERE, Capability.TRAUMA))
    s = SimulationState.from_scenario(sc)
    s.time_min = 120
    return s


def log_with(handovers, starts):
    log = EventLog("t")
    for t, vids in handovers.items():
        log.record(t, "handover_complete", ambulance_id="AMB-01", hospital_id="H-T", victim_ids=vids)
    for vid, t in starts.items():
        log.record(t, "treatment_started", victim_id=vid, hospital_id="H-T", doctor_id="D", nurse_id="N")
    return log


def test_p1_counts_all_critical_victims_and_p2_only_treated_ones(tiny_scenario):
    s = state_with(tiny_scenario, extra_critical=2)         # V-01, V-03, V-04 are critical
    log = log_with({30: ["V-01", "V-03"]}, {"V-01": 35, "V-03": 45})   # waits 5 and 15; V-04 never reached a hospital
    m = treatment_wait_metrics(s, log)
    assert m["critical_handed_over"] == 2 and m["critical_never_started"] == 1
    assert m["critical_treated_within_n_rate"] == pytest.approx(1 / 3)       # denominator is all 3 critical victims
    assert m["critical_treatment_wait_mean"] == pytest.approx(10.0)          # treated only: (5 + 15) / 2


def test_arrived_but_never_started_counts_as_not_in_time_and_empty_runs_are_none(tiny_scenario):
    s = state_with(tiny_scenario)
    m = treatment_wait_metrics(s, log_with({115: ["V-01"]}, {}))
    assert m["critical_treated_within_n_rate"] == 0 and m["critical_never_started"] == 1
    assert m["critical_treatment_wait_mean"] is None


def loan_message(mid, nid, mtype, sender, recipient, s_inst=None, r_inst=None, rnd=1, reason="x"):
    m = dict(kind="agent_message", t=12, message_id=mid, negotiation_id=nid, message_type=mtype, sender=sender,
             recipient=recipient, round=rnd, reason=reason, incident_id="INC-02")
    if s_inst:
        m["sender_instance"] = s_inst
    if r_inst:
        m["recipient_instance"] = r_inst
    return m


def test_loan_counters_are_separate_from_conflict_and_admission_counters(tiny_scenario):
    s = state_with(tiny_scenario)
    log = EventLog("t")
    h = "hospital_coordination"
    for e in [loan_message("t012-M0001", "LN-t012-01", "request", h, h, "H-T", "H-G"),
              loan_message("t012-M0002", "LN-t012-01", "counter_proposal", h, h, "H-G", "H-T"),
              loan_message("t012-M0003", "LN-t012-01", "accept", h, h, "H-T", "H-G", rnd=2),
              loan_message("t012-M0004", "LN-t012-02", "request", h, h, "H-T", "H-X"),
              loan_message("t012-M0005", "LN-t012-02", "reject", h, h, "H-X", "H-T"),
              loan_message("t012-M0006", "LN-t012-03", "request", h, h, "H-T", "H-G"),
              loan_message("t012-M0007", "LN-t012-03", "accept", h, h, "H-G", "H-T")]:
        log.events.append({"t": 12, **e})
    log.record(12, "loan_started", loan_id="L-01", lender_id="H-G", borrower_id="H-T", capability="general", teams=2,
               staff_ids=[], arrive_min=30, ends_min=60)
    log.record(12, "loan_resolved", negotiation_id="LN-t012-03", method="arbitrated")
    log.record(12, "loan_fallback", stage="rule")
    m = compute_metrics(s, log, "negotiation")
    assert (m.loan_requests, m.loans_accepted, m.loans_rejected, m.loans_countered) == (3, 1, 1, 1)
    assert m.loan_counters_accepted == 1 and m.loan_rounds_max == 2
    assert (m.loans_executed, m.loan_team_minutes, m.loans_arbitrated, m.loan_fallbacks) == (1, 60, 1, 1)
    assert m.negotiations == 0 and m.counter_proposals == 0 and m.admission_requests == 0


def test_old_rows_without_loan_fields_still_describe_no_loans(tiny_scenario):
    m = compute_metrics(state_with(tiny_scenario), EventLog("t"), "naive")
    assert m.loan_requests == 0 and m.loans_executed == 0 and m.loan_rounds_mean is None
