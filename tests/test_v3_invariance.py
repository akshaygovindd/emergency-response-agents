"""Tests: adding v3 must not change v1/v2 in any way (state fingerprints, prompts, messages, logs, results, cache keys).

Golden values were computed on the untouched code before v3 existed. Cached reruns run with the model client
replaced by a function that raises, so a cache miss fails the test: these tests can never spend tokens.
"""
import hashlib
import json
import subprocess

import pytest
from pydantic import ValidationError

import erc.config as config
from erc.agents import llm_cache
from erc.agents.assessment import oracle_assessment
from erc.agents.context import AgentContext, state_fingerprint
from erc.agents.prompts import dispatch_prompt, hospital_prompt
from erc.config import PROJECT_ROOT, Mode, ScenarioName
from erc.eval import experiment as exp
from erc.eval.metrics import compute_metrics
from erc.models.messages import ActionType, AgentMessage, AgentName, MessageType, ProposedAction
from erc.models.state import SimulationState
from erc.sim.engine import Engine


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def surge_state():
    st = SimulationState.from_scenario(exp.load_scenario(ScenarioName.SURGE, 42))
    st.time_min = 12
    return st


# ───────── state, prompts, serialisation ─────────
def test_state_fingerprint_and_v2_prompts_are_unchanged():
    st = surge_state()
    assert state_fingerprint(st) == "7ee7446b537b746e"
    ctx = AgentContext(state=st, assessments={i.incident_id: oracle_assessment(i) for i in st.visible_incidents()},
                       round_id="t012")
    assert digest(dispatch_prompt(ctx)) == "122cbe56977de782"
    assert digest(hospital_prompt(ctx)) == "75b84d3ac8850789"


def test_loan_bookkeeping_never_enters_the_state_dump():
    st = surge_state()
    assert "staff_loans" not in st.model_dump()
    assert "staff_loans" not in st.model_dump_json()


def test_old_messages_and_actions_serialise_exactly_as_before():
    a = ProposedAction(action_type=ActionType.ASSIGN_AMBULANCE, ambulance_id="AMB-01", victim_ids=["V-01-1"])
    m = AgentMessage(sender=AgentName.DISPATCH, recipient=AgentName.RESOURCE_ALLOCATION, message_type=MessageType.PROPOSAL,
                     incident_id="INC-01", proposed_action=a, message_id="t001-M0001", timestamp_min=1, priority=2, reason="x")
    assert json.dumps(a.model_dump(mode="json"), sort_keys=True) == (
        '{"action_type": "assign_ambulance", "ambulance_id": "AMB-01", "hospital_id": null, "responder_id": null, '
        '"victim_ids": ["V-01-1"]}')
    assert json.dumps(m.model_dump(mode="json"), sort_keys=True) == (
        '{"alternative": null, "deadline_min": null, "in_reply_to": null, "incident_id": "INC-01", "message_id": "t001-M0001", '
        '"message_type": "proposal", "negotiation_id": null, "priority": 2, "proposed_action": {"action_type": "assign_ambulance", '
        '"ambulance_id": "AMB-01", "hospital_id": null, "responder_id": null, "victim_ids": ["V-01-1"]}, "reason": "x", '
        '"recipient": "resource_allocation", "round": 0, "sender": "dispatch", "timestamp_min": 1}')


def message(**kw):
    base = dict(sender=AgentName.HOSPITAL, recipient=AgentName.HOSPITAL, message_type=MessageType.INFO, incident_id="INC-01",
                message_id="M-1", timestamp_min=1, priority=2, reason="x")
    return AgentMessage(**{**base, **kw})


def test_self_message_rule_is_relaxed_only_for_distinct_instances():
    ok = message(sender_instance="H-T", recipient_instance="H-G")
    assert ok.sender_id == "hospital_coordination:H-T" and ok.recipient_id == "hospital_coordination:H-G"
    dumped = ok.model_dump(mode="json")
    assert dumped["sender_id"] == "hospital_coordination:H-T" and dumped["recipient_id"] == "hospital_coordination:H-G"
    with pytest.raises(ValidationError):
        message(sender_instance="H-T", recipient_instance="H-T")      # the same instance
    with pytest.raises(ValidationError):
        message()                                                     # no instances: still no self-messages
    with pytest.raises(ValidationError):
        message(sender=AgentName.DISPATCH, recipient=AgentName.DISPATCH, sender_instance="H-T", recipient_instance="H-T")


# ───────── baselines and agent systems reproduce saved v1/v2 logs byte for byte ─────────
def saved(version: str, mode: str, name: str) -> str:
    return (PROJECT_ROOT / "logs" / version / mode / name).read_text()


def as_text(log) -> str:
    return "".join(json.dumps(e) + "\n" for e in log.events)


@pytest.mark.parametrize("mode", [Mode.NAIVE, Mode.GREEDY])
@pytest.mark.parametrize("version", ["v2", "v3"])
def test_baselines_in_v2_and_v3_equal_the_saved_v2_logs(mode, version):
    engine = Engine(exp.load_scenario(ScenarioName.BOTTLENECK, 42), exp.make_policy(mode, version))
    engine.run()
    assert as_text(engine.log) == saved("v2", mode.value, f"bottleneck_seed42_{mode.value}.jsonl")


def no_api(monkeypatch):
    async def miss(*a, **k):
        raise AssertionError("cache miss: this test must never reach the model")
    monkeypatch.setattr(llm_cache.Runner, "run", miss)


@pytest.mark.parametrize("version,mode,scenario", [
    ("v1", Mode.AGENTS, ScenarioName.NORMAL), ("v1", Mode.NEGOTIATION, ScenarioName.NORMAL),
    ("v2", Mode.AGENTS, ScenarioName.BOTTLENECK), ("v2", Mode.NEGOTIATION, ScenarioName.BOTTLENECK),
    ("v2", Mode.AGENTS, ScenarioName.SURGE)])
def test_cached_agent_reruns_reproduce_saved_logs_and_metrics(monkeypatch, version, mode, scenario):
    no_api(monkeypatch)
    engine = Engine(exp.load_scenario(scenario, 42), exp.make_policy(mode, version))
    engine.run()
    name = f"{scenario.value}_seed42_{mode.value}.jsonl"
    assert as_text(engine.log) == saved(version, mode.value, name)
    row = next(r for r in exp.load_runs(version) if (r["scenario"], r["seed"], r["mode"]) == (scenario.value, 42, mode.value))
    now = compute_metrics(engine.state, engine.log, mode.value).model_dump(mode="json")
    assert {k: now[k] for k in row if k != "version"} == {k: v for k, v in row.items() if k != "version"}


# ───────── isolation ─────────
def test_v1_and_v2_are_protected_and_v3_writes_only_under_v3(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    for version in ("v1", "v2"):
        with pytest.raises(PermissionError):
            config.require_writable(version)
    exp.run_one(ScenarioName.BOTTLENECK, 42, Mode.NAIVE, "v3")
    exp.save_runs([exp.run_one(ScenarioName.BOTTLENECK, 42, Mode.GREEDY, "v3")], "v3")
    files = {p.relative_to(tmp_path).parts[1] for p in tmp_path.rglob("*") if p.is_file()}
    assert files == {"v3"}


def test_saved_v1_v2_results_and_logs_equal_the_final_submission_tag():
    tag = subprocess.run(["git", "rev-parse", "--verify", "-q", "final-submission"], cwd=PROJECT_ROOT,
                         capture_output=True, text=True)
    if tag.returncode != 0:
        pytest.skip("final-submission tag not available (shallow clone)")
    diff = subprocess.run(["git", "diff", "--exit-code", "--stat", "final-submission", "--",
                           "results/v1", "results/v2", "logs/v1", "logs/v2"],
                          cwd=PROJECT_ROOT, capture_output=True, text=True)
    assert diff.returncode == 0, diff.stdout
