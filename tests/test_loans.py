"""Tests: v3 staff loans (physics, validator, protocol). Offline: fake LLM answers, nothing written to results/ or logs/."""
import asyncio

import pytest

from erc.agents import loans as LP
from erc.agents.assessment import oracle_assessment
from erc.agents.context import AgentContext
from erc.agents.llm_cache import LLMResult
from erc.agents.system import AgentSystem
from erc.config import ScenarioName
from erc.logging.event_log import EventLog
from erc.models.entities import (
    Capability as C, Hospital, Incident, IncidentType, LoanPhase, Severity, SkillLevel, StaffMember, StaffRole,
    VictimStatus,
)
from erc.models.messages import ActionType, LoanSpec, ProposedAction, RejectionReason as R
from erc.models.state import SimulationState
from erc.sim import loans as SL
from erc.sim.engine import Decision, Engine
from erc.sim.validator import validate
from tests.conftest import loc, victim


class Idle:
    name = "idle"


def answer(output):
    return LLMResult(output, 0, 0, 0.0, False, 1)


def staff(sid, role, hospital, level=SkillLevel.EXPERT, max_patients=2):
    return StaffMember(staff_id=sid, role=role, hospital_id=hospital,
                       skills={C.GENERAL: level, C.TRAUMA: SkillLevel.INTERMEDIATE}, max_patients=max_patients)


@pytest.fixture
def world(tiny_scenario):
    """H-T (borrower, one general slot) has two general patients queued; H-G and H-X can lend."""
    sc = tiny_scenario.model_copy(deep=True)
    sc.hospitals = [
        Hospital(hospital_id="H-T", name="Trauma Center", location=loc(5, 5), er_capacity=4,
                 treatment_slots={C.TRAUMA: 2, C.GENERAL: 1}, beds=6),
        Hospital(hospital_id="H-G", name="General Hospital", location=loc(15, 15), er_capacity=6,
                 treatment_slots={C.GENERAL: 3}, beds=10),
        Hospital(hospital_id="H-X", name="Extra Hospital", location=loc(10, 5), er_capacity=6,
                 treatment_slots={C.GENERAL: 2}, beds=8),
    ]
    sc.staff = [staff("D-T", StaffRole.DOCTOR, "H-T", max_patients=3), staff("N-T", StaffRole.NURSE, "H-T"),
                staff("D-G1", StaffRole.DOCTOR, "H-G", max_patients=3), staff("D-G2", StaffRole.DOCTOR, "H-G", max_patients=3),
                staff("N-G1", StaffRole.NURSE, "H-G"), staff("N-G2", StaffRole.NURSE, "H-G"),
                staff("D-X1", StaffRole.DOCTOR, "H-X", max_patients=3), staff("N-X1", StaffRole.NURSE, "H-X")]
    inc = sc.incidents[1]
    sc.incidents[1] = Incident(incident_id="INC-02", incident_type=IncidentType.BUILDING_FIRE, location=loc(12, 8),
                               arrival_time_min=10, victims=[victim("V-02", "INC-02", Severity.SERIOUS, C.GENERAL),
                                                             victim("V-03", "INC-02", Severity.MODERATE, C.GENERAL)])
    return sc


def queue_state(world, occupied=True):
    """State at minute 12: V-02 and V-03 sit in H-T's ER, its only general slot is busy."""
    s = SimulationState.from_scenario(world)
    s.time_min = 12
    for vid in ("V-02", "V-03"):
        s.find_victim(vid).status = VictimStatus.AWAITING_TREATMENT
        s.admissions[vid] = "H-T"
    h = s.hospitals["H-T"]
    h.er_occupied = 2
    if occupied:
        h.treatment_occupied = {C.GENERAL: 1}
        h.beds_occupied = 1
    return s


def spec(lender="H-G", teams=1, duration=30, borrower="H-T", cap=C.GENERAL):
    return LoanSpec(lender_id=lender, borrower_id=borrower, capability=cap, teams=teams, duration_min=duration)


def reason(result):
    return None if result.accepted else result.reason


# ───────── trigger and hard rules ─────────
def test_need_is_detected_with_feasible_lenders(world):
    [need] = SL.open_needs(queue_state(world))
    assert (need.borrower_id, need.capability, need.uncovered) == ("H-T", C.GENERAL, 2)
    assert need.lenders == ["H-X", "H-G"]                 # nearest first


def test_no_need_when_a_slot_is_free_or_nobody_is_queued(world):
    assert SL.open_needs(queue_state(world, occupied=False)) == []
    s = queue_state(world)
    for vid in ("V-02", "V-03"):
        s.find_victim(vid).status = VictimStatus.WAITING
    assert SL.open_needs(s) == []


def test_valid_loan_passes_and_each_rule_has_a_reason_code(world):
    s = queue_state(world)
    assert SL.check_loan(s, spec()).accepted
    assert reason(SL.check_loan(s, spec(teams=3))) == R.MALFORMED
    assert reason(SL.check_loan(s, spec(duration=10))) == R.MALFORMED
    assert reason(SL.check_loan(s, spec(lender="H-T"))) == R.MALFORMED
    assert reason(SL.check_loan(s, spec(lender="H-Q"))) == R.UNKNOWN_RESOURCE
    assert reason(SL.check_loan(s, spec(cap=C.BURN))) == R.HOSPITAL_LACKS_CAPABILITY
    assert reason(SL.check_loan(s, spec(teams=2, lender="H-X"))) == R.STAFF_UNAVAILABLE      # H-X has one team only


def test_loan_not_needed_without_a_blocked_queue(world):
    assert reason(SL.check_loan(queue_state(world, occupied=False), spec())) == R.LOAN_NOT_NEEDED


def test_lender_needs_an_idle_slot_of_that_care_type(world):
    s = queue_state(world)
    g = s.hospitals["H-G"]
    g.treatment_occupied = {C.GENERAL: 3}
    g.beds_occupied = 3
    assert reason(SL.check_loan(s, spec())) == R.LENDER_NO_IDLE_SLOT


def test_lender_needs_idle_qualified_staff(world):
    s = queue_state(world)
    s.staff["D-G1"].current_patients = 1
    s.staff["D-G2"].on_shift = False
    assert reason(SL.check_loan(s, spec())) == R.STAFF_UNAVAILABLE


def test_staff_already_on_loan_cannot_be_lent_again(world):
    s = queue_state(world)
    eng = Engine(world, Idle())
    eng.state = s
    eng.staff_loans = True
    eng._start_loan(spec())
    assert {"D-G1", "N-G1"} <= SL.on_loan_ids(s)
    picked = SL.pick_staff(s, spec(teams=1))
    assert picked == (["D-G2"], ["N-G2"])


def test_borrower_beds_cap(world):
    s = queue_state(world)
    s.hospitals["H-T"].beds = 3                      # 3 slots already = 3 beds
    assert reason(SL.check_loan(s, spec())) == R.BORROWER_BEDS_FULL


def test_lender_keeps_its_last_slot_when_it_has_own_patients(world):
    s = queue_state(world)
    s.hospitals["H-G"].treatment_slots = {C.GENERAL: 1}
    assert SL.check_loan(s, spec()).accepted                           # its last general slot, but no general patient there
    s.find_victim("V-01").required_capability = C.GENERAL
    s.find_victim("V-01").status = VictimStatus.AWAITING_TREATMENT     # a general patient is queued at H-G
    s.admissions["V-01"] = "H-G"
    s.hospitals["H-G"].er_occupied = 1
    assert reason(SL.check_loan(s, spec())) == R.LENDER_UNDERSTAFFED


def test_lender_headroom_must_cover_patients_it_holds(world):
    s = queue_state(world)
    for sid in ("D-G1", "D-G2"):
        s.staff[sid].max_patients = 1                # H-G's doctors can carry one patient each
    for vid in ("V-05", "V-06"):                     # H-G holds two patients still on the road to it
        s.admissions[vid] = "H-G"
    s.incidents["INC-02"].victims += [victim(vid, "INC-02", Severity.MINOR, C.GENERAL) for vid in ("V-05", "V-06")]
    for vid in ("V-05", "V-06"):
        s.find_victim(vid).status = VictimStatus.IN_TRANSPORT
    # lending one team leaves one doctor with headroom 1 for two patients
    assert reason(SL.check_loan(s, spec())) == R.LENDER_UNDERSTAFFED
    s.admissions.pop("V-06")
    assert SL.check_loan(s, spec()).accepted


def test_ledger_stops_one_slot_being_lent_twice(world):
    s = queue_state(world)
    s.hospitals["H-G"].treatment_occupied = {C.GENERAL: 2}      # exactly one idle general slot left
    s.hospitals["H-G"].beds_occupied = 2
    ledger = SL.Ledger()
    first = spec(teams=1)
    assert SL.check_loan(s, first, ledger).accepted
    ledger.reserve(first, *SL.pick_staff(s, first, ledger))
    assert reason(SL.check_loan(s, spec(), ledger)) == R.LENDER_NO_IDLE_SLOT


def test_validator_dispatches_loan_actions(world):
    s = queue_state(world)
    action = ProposedAction(action_type=ActionType.LOAN_STAFF, loan=spec())
    assert validate(action, "INC-02", s).accepted
    with pytest.raises(ValueError):
        ProposedAction(action_type=ActionType.LOAN_STAFF)         # a loan action needs its terms


# ───────── engine physics ─────────
def run_minutes(eng, start, end):
    for t in range(start, end + 1):
        eng.state.time_min = t
        eng._finish_treatments(t)
        eng._advance_loans(t)
        eng._start_treatments(t)


def test_loan_lifecycle_moves_slot_and_staff_and_returns_them(world):
    s = queue_state(world)
    eng = Engine(world, Idle())
    eng.state, eng.staff_loans = s, True
    eng._handle(Decision(ProposedAction(action_type=ActionType.LOAN_STAFF, loan=spec(duration=20)), "INC-02"))
    [ln] = s.staff_loans.values()
    assert s.hospitals["H-G"].treatment_slots[C.GENERAL] == 2          # lender lost a slot immediately
    assert not s.staff["D-G1"].on_shift and not s.staff["N-G1"].on_shift   # travelling
    assert s.hospitals["H-T"].treatment_slots[C.GENERAL] == 1          # borrower has not gained it yet
    assert ln.phase == LoanPhase.TRANSFER_OUT and ln.arrive_min > 12

    run_minutes(eng, 12, ln.arrive_min)
    assert ln.phase == LoanPhase.ACTIVE
    assert s.hospitals["H-T"].treatment_slots[C.GENERAL] == 2          # borrower gained the slot
    assert s.staff["D-G1"].hospital_id == "H-T" and s.staff["D-G1"].on_shift
    assert s.find_victim("V-02").status == VictimStatus.IN_TREATMENT or s.find_victim("V-03").status == VictimStatus.IN_TREATMENT

    run_minutes(eng, ln.arrive_min + 1, ln.ends_min)
    assert ln.phase in (LoanPhase.RECALLED, LoanPhase.TRANSFER_BACK)
    assert not s.staff["D-G1"].on_shift or ln.phase == LoanPhase.TRANSFER_BACK
    run_minutes(eng, ln.ends_min + 1, 119)
    assert ln.phase == LoanPhase.RETURNED
    assert s.hospitals["H-T"].treatment_slots[C.GENERAL] == 1          # extra slot withdrawn
    assert s.hospitals["H-G"].treatment_slots[C.GENERAL] == 3          # lender's slot back
    assert s.staff["D-G1"].hospital_id == "H-G" and s.staff["D-G1"].on_shift
    assert [e["kind"] for e in eng.log.events if e["kind"].startswith("loan_")] == [
        "loan_started", "loan_arrived", "loan_recalled", "loan_returning", "loan_returned"]


def test_extra_slot_is_never_removed_while_occupied(world):
    s = queue_state(world)
    eng = Engine(world, Idle())
    eng.state, eng.staff_loans = s, True
    eng._handle(Decision(ProposedAction(action_type=ActionType.LOAN_STAFF, loan=spec(duration=20)), "INC-02"))
    [ln] = s.staff_loans.values()
    run_minutes(eng, 12, ln.ends_min)
    h = s.hospitals["H-T"]
    # the loaned slot is in use (the original general patient still occupies slot 1); recall must wait
    assert h.treatment_occupied.get(C.GENERAL, 0) <= h.treatment_slots[C.GENERAL]
    if h.treatment_occupied.get(C.GENERAL, 0) == 2:
        assert ln.slots_open == 1 and ln.phase == LoanPhase.RECALLED


def test_signature_wakes_the_policy_only_with_loans_enabled(world):
    quiet = queue_state(world)
    quiet.find_victim("V-01").status = VictimStatus.TREATED       # nothing for ambulances or teams to do
    quiet.responders["FIRE-1"].status = quiet.responders["FIRE-1"].status
    eng_off = Engine(world, Idle())
    eng_off.state = quiet
    assert eng_off._decision_signature() is None
    eng_on = Engine(world, Idle(), staff_loans=True)
    eng_on.state = quiet
    assert eng_on._decision_signature() is not None


# ───────── protocol (fake LLM) ─────────
def make_system(world, negotiate, asks=None, answers=None, revisions=None, allocation=None, state=None):
    s = state or queue_state(world)
    s.find_victim("V-02")
    reports = {i.incident_id: oracle_assessment(i) for i in s.visible_incidents()}
    ctx = AgentContext(state=s, assessments=reports, round_id="t012")
    sys_ = AgentSystem(negotiate=negotiate, oracle=True, loan_protocol="v3")
    sys_.bind_log(EventLog("test"))
    prompts = {}

    def stub(name, output):
        async def f(prompt):
            prompts.setdefault(name, []).append(prompt)
            if output is None:
                raise AssertionError(f"{name} must not be called")
            return answer(output(prompt) if callable(output) else output)
        return f
    LP.ask_asks = stub("asks", asks)
    LP.ask_answers = stub("answers", answers)
    LP.ask_revisions = stub("revisions", revisions)
    LP.ask_allocation = stub("allocation", allocation)
    return ctx, sys_, prompts


@pytest.fixture(autouse=True)
def restore_llm():
    saved = (LP.ask_asks, LP.ask_answers, LP.ask_revisions, LP.ask_allocation)
    yield
    LP.ask_asks, LP.ask_answers, LP.ask_revisions, LP.ask_allocation = saved


def ask(lender="H-G", teams=1, duration=30):
    return {"asks": [{"care": "general", "lender_id": lender, "teams": teams, "duration_min": duration, "reason": "queue"}]}


def decide(ctx, sys_):
    return asyncio.run(sys_._negotiate_loans(ctx))


def msgs(sys_):
    return sys_.log.of_kind("agent_message")


def test_agents_mode_uses_the_fixed_rule_and_no_lender_llm(world):
    ctx, sys_, prompts = make_system(world, False, asks=ask())
    [d] = decide(ctx, sys_)
    assert d.action.action_type == ActionType.LOAN_STAFF and d.action.loan.lender_id == "H-G"
    assert d.source == "hospital_coordination:H-T"
    kinds = [(m["message_type"], m.get("sender_id", m["sender"]), m.get("recipient_id", m["recipient"])) for m in msgs(sys_)]
    assert kinds == [("request", "hospital_coordination:H-T", "hospital_coordination:H-G"),
                     ("accept", "hospital_coordination:H-G", "hospital_coordination:H-T"),
                     ("commit", "resource_allocation", "hospital_coordination:H-T")]
    assert "answers" not in prompts and "revisions" not in prompts and "allocation" not in prompts


def test_agents_mode_rule_rejects_when_lender_has_critical_patients_then_redirects(world):
    s = queue_state(world)
    s.find_victim("V-01").status = VictimStatus.IN_TRANSPORT
    s.admissions["V-01"] = "H-G"
    s.find_victim("V-01").required_capability = C.GENERAL            # critical, en route to H-G
    ctx, sys_, _ = make_system(world, False, asks=ask("H-G"), state=s)
    [d] = decide(ctx, sys_)
    assert d.action.loan.lender_id == "H-X"                              # the rule redirected
    assert [e["method"] for e in sys_.log.of_kind("loan_resolved")] == ["redirect"]
    assert len(sys_.log.of_kind("loan_redirect")) == 1


def test_negotiation_lender_counters_and_borrower_accepts(world):
    ctx, sys_, prompts = make_system(
        world, True, asks=ask(teams=2, duration=60),
        answers=lambda p: {"answers": [{"request_id": "LN-t012-01", "decision": "counter", "teams": 1,
                                        "duration_min": 25, "reason": "keep a team for my own patients"}]},
        revisions={"revisions": [{"request_id": "LN-t012-01", "action": "accept_counter", "lender_id": "none",
                                  "teams": 1, "duration_min": 25, "reason": "fine"}]})
    [d] = decide(ctx, sys_)
    assert (d.action.loan.teams, d.action.loan.duration_min) == (1, 25)
    types = [m["message_type"] for m in msgs(sys_)]
    assert types == ["request", "counter_proposal", "accept", "commit"]
    assert sys_.log.of_kind("loan_resolved")[0]["method"] == "counter_accepted"


def test_negotiation_reject_then_request_other_lender(world):
    ctx, sys_, _ = make_system(
        world, True, asks=ask("H-G"),
        answers=lambda p: {"answers": [{"request_id": "LN-t012-01",
                                        "decision": "reject" if '"hospital_id":"H-G"' in p else "accept",
                                        "teams": 1, "duration_min": 30, "reason": "x"}]},
        revisions={"revisions": [{"request_id": "LN-t012-01", "action": "request_other", "lender_id": "H-X",
                                  "teams": 1, "duration_min": 30, "reason": "try X"}]})
    [d] = decide(ctx, sys_)
    assert d.action.loan.lender_id == "H-X"
    assert sys_.log.of_kind("loan_resolved")[0]["rounds"] == 2


def test_unresolved_after_three_rounds_goes_to_arbitration(world):
    always_reject = lambda p: {"answers": [{"request_id": "LN-t012-01", "decision": "reject", "teams": 1,
                                            "duration_min": 30, "reason": "no"}]}
    ctx, sys_, prompts = make_system(
        world, True, asks=ask("H-G"), answers=always_reject,
        revisions={"revisions": [{"request_id": "LN-t012-01", "action": "escalate", "lender_id": "none",
                                  "teams": 1, "duration_min": 30, "reason": "stuck"}]},
        allocation={"allocations": [{"request_id": "LN-t012-01", "lender_id": "H-X", "teams": 1, "duration_min": 30,
                                     "reason": "X can spare"}]})
    [d] = decide(ctx, sys_)
    assert d.action.loan.lender_id == "H-X"
    assert sys_.log.of_kind("loan_resolved")[0]["method"] == "arbitrated"
    assert any(m["message_type"] == "escalate" for m in msgs(sys_))


def test_invalid_arbitration_falls_back_to_the_rule(world):
    ctx, sys_, _ = make_system(
        world, True, asks=ask("H-G"),
        answers=lambda p: {"answers": [{"request_id": "LN-t012-01", "decision": "reject", "teams": 1, "duration_min": 30, "reason": "no"}]},
        revisions={"revisions": [{"request_id": "LN-t012-01", "action": "escalate", "lender_id": "none", "teams": 1, "duration_min": 30, "reason": "s"}]},
        allocation={"allocations": [{"request_id": "LN-t012-01", "lender_id": "H-Z", "teams": 1, "duration_min": 30, "reason": "?"}]})
    [d] = decide(ctx, sys_)
    assert sys_.log.of_kind("loan_resolved")[0]["method"] == "fallback" and d.action.loan.lender_id == "H-X"


def test_unparseable_output_never_crashes_and_never_strands(world):
    ctx, sys_, _ = make_system(world, True, asks={"nonsense": 1}, answers={"nonsense": 1}, revisions={"nonsense": 1},
                               allocation={"nonsense": 1})
    [d] = decide(ctx, sys_)
    assert d.action.loan.borrower_id == "H-T"
    assert len(sys_.log.of_kind("loan_fallback")) >= 1


def test_infeasible_ask_is_dropped_and_the_rule_asks_instead(world):
    ctx, sys_, _ = make_system(world, False, asks=ask(lender="H-Q"))
    [d] = decide(ctx, sys_)
    assert d.action.loan.lender_id == "H-X"
    assert sys_.log.of_kind("proposal_invalid")


def test_instances_only_see_their_own_hospital(world):
    ctx, sys_, prompts = make_system(
        world, True, asks=ask("H-G"),
        answers=lambda p: {"answers": [{"request_id": "LN-t012-01", "decision": "accept", "teams": 1, "duration_min": 30, "reason": "ok"}]})
    decide(ctx, sys_)
    borrower_prompt, lender_prompt = prompts["asks"][0], prompts["answers"][0]
    assert '"hospital_id":"H-T"' in borrower_prompt and "D-G1" not in borrower_prompt and '"free":3' not in borrower_prompt
    assert '"hospital_id":"H-G"' in lender_prompt
    assert "V-02" not in lender_prompt and "V-03" not in lender_prompt          # the borrower's queue is not shared
    assert "deadline" not in borrower_prompt + lender_prompt


def test_contention_for_one_slot_goes_to_the_more_urgent_request(world):
    s = queue_state(world)
    # H-X also needs a general slot: its patient is critical; H-G has exactly one idle general slot to give
    s.hospitals["H-G"].treatment_occupied = {C.GENERAL: 2}
    s.hospitals["H-G"].beds_occupied = 2
    s.hospitals["H-X"].treatment_slots = {C.GENERAL: 1}
    s.hospitals["H-X"].treatment_occupied = {C.GENERAL: 1}
    s.hospitals["H-X"].beds_occupied = 1
    s.hospitals["H-X"].er_occupied = 1
    s.find_victim("V-01").required_capability = C.GENERAL
    s.find_victim("V-01").status = VictimStatus.AWAITING_TREATMENT
    s.admissions["V-01"] = "H-X"
    s.admissions.pop("V-03")
    s.find_victim("V-03").status = VictimStatus.WAITING
    s.hospitals["H-T"].er_occupied = 1
    ctx, sys_, _ = make_system(world, False, state=s, asks=lambda p: ask("H-G"))
    decisions = decide(ctx, sys_)
    contention = sys_.log.of_kind("loan_contention")
    assert contention and contention[0]["method"] == "priority_rule"
    assert [d.action.loan.borrower_id for d in decisions] == ["H-X"]            # critical patient wins the single slot
