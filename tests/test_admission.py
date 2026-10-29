"""Tests: v2 hospital admission negotiation, run offline with fake LLM answers (no API calls, no files written)."""
import asyncio
import json

import pytest

from erc.agents import admission as A
from erc.agents import system
from erc.agents import tools as T
from erc.agents.assessment import oracle_assessment
from erc.agents.context import AgentContext
from erc.agents.llm_cache import LLMResult
from erc.agents.system import AgentSystem
from erc.config import Mode, ScenarioName
from erc.dashboard.feed import to_feed_item
from erc.eval.experiment import load_scenario, make_policy
from erc.eval.metrics import RunMetrics, compute_metrics
from erc.logging.event_log import EventLog
from erc.models.entities import VictimStatus
from erc.models.state import SimulationState
from erc.sim.engine import Engine

FAKE = LLMResult("fake", 0, 0, 0.0, False, 1)


def answer(output):
    return LLMResult(output, 0, 0, 0.0, False, 1)


def setup(scenario, negotiate, er_taken=0):
    """Both victims reserved on ambulances; H-T has `er_taken` ER beds used (capacity 4)."""
    state = SimulationState.from_scenario(scenario)
    state.time_min = 10
    state.hospitals["H-T"].er_occupied = er_taken
    state.reservations.update({"V-01": "AMB-01", "V-02": "AMB-02"})
    reports = {i.incident_id: oracle_assessment(i) for i in state.visible_incidents()}
    ctx = AgentContext(state=state, assessments=reports, round_id="t010")
    sys_ = AgentSystem(negotiate=negotiate, oracle=True, admission_protocol="v2")
    sys_.bind_log(EventLog("test"))
    return ctx, sys_


def request(ctx, hospital_id, victim_ids):
    n = len(ctx.proposals)
    assert T.propose_destination(ctx, hospital_id, victim_ids, "dispatch wants it").startswith("ACCEPTED")
    return ctx.proposals.pop(n)


def run(ctx, sys_, requests):
    return asyncio.run(A.AdmissionProtocol(sys_, sys_.negotiate).run(ctx, requests))


def msgs(sys_, nid=None):
    out = sys_.log.of_kind("agent_message")
    return [m for m in out if nid is None or m["negotiation_id"] == nid]


def two_requests_one_bed(tiny_scenario, negotiate):
    """H-T has one bed left; trauma victim V-01 needs it, general victim V-02 asked for it too."""
    ctx, sys_ = setup(tiny_scenario, negotiate, er_taken=3)
    return ctx, sys_, [request(ctx, "H-T", ["V-01"]), request(ctx, "H-T", ["V-02"])]


# ───────── Dispatch request tool ─────────
def test_request_for_incapable_or_full_hospital_is_refused(tiny_scenario):
    ctx, _ = setup(tiny_scenario, False)
    assert T.propose_destination(ctx, "H-G", ["V-01"], "x").startswith("REJECTED")     # no trauma care at H-G
    ctx.state.hospitals["H-T"].er_occupied = 4
    assert T.propose_destination(ctx, "H-T", ["V-01"], "x").startswith("REJECTED")     # ER full
    assert len(ctx.invalid) == 2 and not ctx.proposals


# ───────── agents mode: fixed rule, no LLM ─────────
def test_agents_mode_rule_accepts_without_llm(tiny_scenario, monkeypatch):
    async def boom(prompt):
        raise AssertionError("agents mode must not call an LLM")
    for name in ("ask_review", "ask_revision", "ask_arbiter"):
        monkeypatch.setattr(A, name, boom)
    ctx, sys_ = setup(tiny_scenario, False)
    [p] = run(ctx, sys_, [request(ctx, "H-G", ["V-02"])])
    assert p.action.hospital_id == "H-G" and p.action.victim_ids == ["V-02"]
    kinds = [(m["sender"], m["recipient"], m["message_type"]) for m in msgs(sys_)]
    assert kinds == [("dispatch", "hospital_coordination", "proposal"),
                     ("hospital_coordination", "dispatch", "accept")]


def test_agents_mode_rule_redirects_when_hospital_filled(tiny_scenario):
    ctx, sys_, reqs = two_requests_one_bed(tiny_scenario, False)
    done = run(ctx, sys_, reqs)
    assert {p.action.victim_ids[0]: p.action.hospital_id for p in done} == {"V-01": "H-T", "V-02": "H-G"}
    assert [m["message_type"] for m in msgs(sys_) if m["sender"] == "hospital_coordination"] == ["accept", "reject"]
    assert not [m for m in msgs(sys_) if m["message_type"] == "counter_proposal"]
    assert len(sys_.log.of_kind("admission_redirect")) == 1


# ───────── negotiation mode ─────────
def test_ledger_stops_double_accept_and_dispatch_revises(tiny_scenario, monkeypatch):
    rounds = []

    async def review(prompt):
        rounds.append(prompt)
        ids = [r["request_id"] for r in json.loads(prompt.split("\n", 1)[1])["requests"]]
        return answer({"reviews": [{"request_id": i, "decision": "accept", "counter_hospital_id": "none",
                                    "reason": "ok"} for i in ids]})

    async def revision(prompt):
        reqs = json.loads(prompt.split("\n", 1)[1])["requests"]
        assert [o["hospital_id"] for o in reqs[0]["options"]] == ["H-G"]
        return answer({"revisions": [{"request_id": reqs[0]["request_id"], "action": "request_other",
                                      "hospital_id": "H-G", "reason": "other hospital"}]})

    monkeypatch.setattr(A, "ask_review", review)
    monkeypatch.setattr(A, "ask_revision", revision)
    ctx, sys_, reqs = two_requests_one_bed(tiny_scenario, True)
    done = run(ctx, sys_, reqs)
    assert {p.action.victim_ids[0]: p.action.hospital_id for p in done} == {"V-01": "H-T", "V-02": "H-G"}
    assert len(rounds) == 2                                              # round 2 reviewed only the revised request
    [res] = [e for e in sys_.log.of_kind("admission_resolved") if e["victim_ids"] == ["V-02"]]
    assert res["method"] == "revised" and res["rounds"] == 2
    assert max(m["round"] for m in msgs(sys_)) == 2


def test_counter_accepted_by_dispatch(tiny_scenario, monkeypatch):
    async def review(prompt):
        return answer({"reviews": [{"request_id": json.loads(prompt.split("\n", 1)[1])["requests"][0]["request_id"],
                                    "decision": "counter", "counter_hospital_id": "H-G",
                                    "reason": "keep the trauma bed"}]})

    async def revision(prompt):
        rid = json.loads(prompt.split("\n", 1)[1])["requests"][0]["request_id"]
        return answer({"revisions": [{"request_id": rid, "action": "accept_counter", "hospital_id": "none",
                                      "reason": "fine"}]})

    monkeypatch.setattr(A, "ask_review", review)
    monkeypatch.setattr(A, "ask_revision", revision)
    ctx, sys_ = setup(tiny_scenario, True)
    [p] = run(ctx, sys_, [request(ctx, "H-T", ["V-02"])])
    assert p.action.hospital_id == "H-G"
    seq = [(m["sender"], m["message_type"]) for m in msgs(sys_)]
    assert seq == [("dispatch", "proposal"), ("hospital_coordination", "counter_proposal"), ("dispatch", "accept")]
    m = compute_metrics(ctx.state, sys_.log, "negotiation")
    assert (m.admission_requests, m.admissions_countered, m.admission_counters_accepted) == (1, 1, 1)
    assert m.negotiations == 0 and m.counter_proposals == 0              # conflict metrics untouched


def test_infeasible_counter_becomes_reject_then_escalates_to_arbitration(tiny_scenario, monkeypatch):
    async def review(prompt):
        rid = json.loads(prompt.split("\n", 1)[1])["requests"][0]["request_id"]
        return answer({"reviews": [{"request_id": rid, "decision": "counter", "counter_hospital_id": "H-X",
                                    "reason": "elsewhere"}]})

    async def revision(prompt):
        rid = json.loads(prompt.split("\n", 1)[1])["requests"][0]["request_id"]
        return answer({"revisions": [{"request_id": rid, "action": "escalate", "hospital_id": "none", "reason": "stuck"}]})

    async def arbiter(prompt):
        rid = json.loads(prompt.split("\n", 1)[1])["requests"][0]["request_id"]
        return answer({"choices": [{"request_id": rid, "hospital_id": "H-G", "reason": "best"}]})

    monkeypatch.setattr(A, "ask_review", review)
    monkeypatch.setattr(A, "ask_revision", revision)
    monkeypatch.setattr(A, "ask_arbiter", arbiter)
    ctx, sys_ = setup(tiny_scenario, True)
    [p] = run(ctx, sys_, [request(ctx, "H-T", ["V-02"])])
    assert p.action.hospital_id == "H-G"
    kinds = [(m["sender"], m["recipient"], m["message_type"]) for m in msgs(sys_)]
    assert ("hospital_coordination", "dispatch", "reject") in kinds
    assert ("dispatch", "resource_allocation", "escalate") in kinds
    assert ("resource_allocation", "dispatch", "accept") in kinds
    assert {m["sender"] for m in msgs(sys_)} <= {"dispatch", "hospital_coordination", "resource_allocation"}


def test_unusable_llm_answers_fall_back_to_the_rule(tiny_scenario, monkeypatch):
    async def junk(prompt):
        return answer("not json")
    for name in ("ask_review", "ask_revision", "ask_arbiter"):
        monkeypatch.setattr(A, name, junk)
    ctx, sys_, reqs = two_requests_one_bed(tiny_scenario, True)
    done = run(ctx, sys_, reqs)
    assert {p.action.victim_ids[0]: p.action.hospital_id for p in done} == {"V-01": "H-T", "V-02": "H-G"}
    stages = [e.get("stage") for e in sys_.log.of_kind("admission_fallback")]
    assert {"review", "revision", "arbitration", "rule"} <= set(stages)
    assert compute_metrics(ctx.state, sys_.log, "negotiation").admission_fallbacks == len(stages)


def test_nobody_has_room_leaves_request_pending(tiny_scenario):
    ctx, sys_ = setup(tiny_scenario, False)
    req = request(ctx, "H-G", ["V-02"])
    ctx.state.hospitals["H-G"].er_occupied = 6
    ctx.state.hospitals["H-T"].er_occupied = 4
    assert run(ctx, sys_, [req]) == []
    [e] = sys_.log.of_kind("admission_resolved")
    assert e["hospital_id"] is None and e["method"] == "pending"


# ───────── views never leak ground truth ─────────
def test_review_view_has_no_deadlines_or_ground_truth(tiny_scenario):
    ctx, _ = setup(tiny_scenario, True)
    view = json.dumps(T.hospital_review_view(ctx, [], {"H-T": 1}))
    assert "deadline" not in view and "condition" not in view
    assert T.waiting_critical_view(ctx) == []                  # V-01 is reserved, V-02 is not critical
    ctx.state.reservations.pop("V-01")
    assert [v["victim_id"] for v in T.waiting_critical_view(ctx)] == ["V-01"]


# ───────── Whole pipeline, v1 stays v1, baselines unchanged ─────────
async def fake_destination(ctx):
    view = T.hospital_situation(ctx)
    for a in view["ambulances_needing_destination"]:
        if a["est_minutes_to"]:
            hid = min(a["est_minutes_to"], key=a["est_minutes_to"].get)
            T.propose_destination(ctx, hid, [v["victim_id"] for v in a["victims"]], "fake")
    return FAKE if view["ambulances_needing_destination"] else None


@pytest.mark.parametrize("negotiate", [False, True])
def test_v2_pipeline_end_to_end_offline(tiny_scenario, monkeypatch, negotiate):
    from test_system import fake_dispatch

    async def review(prompt):
        reqs = json.loads(prompt.split("\n", 1)[1])["requests"]
        return answer({"reviews": [{"request_id": r["request_id"], "decision": "accept",
                                    "counter_hospital_id": "none", "reason": "ok"} for r in reqs]})

    monkeypatch.setattr(system, "run_dispatch", fake_dispatch)
    monkeypatch.setattr(system, "run_destination", fake_destination)
    monkeypatch.setattr(A, "ask_review", review)
    engine = Engine(tiny_scenario, AgentSystem(negotiate=negotiate, oracle=True, admission_protocol="v2"))
    engine.run()
    assert engine.state.find_victim("V-01").status == VictimStatus.TREATED
    assert not engine.log.of_kind("action_rejected")
    assert engine.log.of_kind("admission_resolved")
    assert all(a["source"] == "dispatch" for a in engine.log.of_kind("action_accepted")
               if a["action"]["action_type"] == "admit_patient")


def test_make_policy_only_changes_agent_systems_in_v2():
    assert make_policy(Mode.NEGOTIATION, "v2").admission_protocol == "v2"
    assert make_policy(Mode.AGENTS, "v2").admission_protocol == "v2"
    assert make_policy(Mode.NEGOTIATION, "v1").admission_protocol == "v1"
    assert not hasattr(make_policy(Mode.GREEDY, "v2"), "admission_protocol")


@pytest.mark.parametrize("scenario,mode", [(s, m) for s in (ScenarioName.NORMAL, ScenarioName.BOTTLENECK)
                                           for m in (Mode.NAIVE, Mode.GREEDY)])
def test_baselines_are_identical_in_v1_and_v2(scenario, mode):
    def metrics(version):
        engine = Engine(load_scenario(scenario, 42), make_policy(mode, version))
        engine.run()
        return compute_metrics(engine.state, engine.log, mode.value).model_dump(exclude={"run_id"})
    assert metrics("v1") == metrics("v2")


# ───────── Metrics and dashboard ─────────
def test_old_v1_rows_still_load(tiny_scenario):
    from erc.policies.naive import NaivePolicy
    engine = Engine(tiny_scenario, NaivePolicy())
    engine.run()
    row = compute_metrics(engine.state, engine.log, "naive").model_dump(mode="json")
    old = {k: v for k, v in row.items() if not k.startswith("admission")}
    assert RunMetrics.model_validate(old).admission_requests == 0


def test_feed_formats_admission_events():
    redirect = to_feed_item({"t": 5, "kind": "admission_redirect", "negotiation_id": "ADM-t005-01",
                             "victim_ids": ["V-02"], "from_hospital": "H-T", "hospital_id": "H-G", "reason": "r"})
    resolved = to_feed_item({"t": 5, "kind": "admission_resolved", "negotiation_id": "ADM-t005-01",
                             "victim_ids": ["V-02"], "hospital_id": "H-G", "method": "counter_accepted", "rounds": 2})
    assert "H-T to H-G" in redirect.text.replace("→", "to") or "H-G" in redirect.text
    assert "counter_accepted" in resolved.text and "2 rounds" in resolved.text
