"""Tests: the full agent pipeline, run offline with deterministic stand-ins for the LLM agents."""
from erc.agents import system
from erc.agents import tools as T
from erc.agents.llm_cache import LLMResult
from erc.agents.system import AgentSystem
from erc.models.entities import VictimStatus
from erc.sim.engine import Engine

FAKE = LLMResult("fake", 0, 0, 0.0, False, 1)


async def fake_dispatch(ctx):
    view = T.dispatch_situation(ctx)
    if not view["incidents"]:
        return None
    for inc in view["incidents"]:
        if inc["nearest_free_ambulances"]:
            amb = inc["nearest_free_ambulances"][0]["ambulance_id"]
            T.propose_ambulance(ctx, amb, inc["incident_id"],
                                [v["victim_id"] for v in inc["waiting_victims"]][:2], 1, "fake")
        if inc["team_needed"] != "none" and inc["team_needed"] not in inc["teams_assigned"]:
            team = next((t["team_id"] for t in view["free_teams"] if t["type"] == inc["team_needed"]), None)
            if team:
                T.propose_team(ctx, team, inc["incident_id"], "fake")
    return FAKE


async def fake_hospital(ctx):
    view = T.hospital_situation(ctx)
    if not view["ambulances_needing_destination"]:
        return None
    for a in view["ambulances_needing_destination"]:
        if a["est_minutes_to"]:
            hid = min(a["est_minutes_to"], key=a["est_minutes_to"].get)
            T.propose_admission(ctx, hid, [v["victim_id"] for v in a["victims"]], "fake")
    return FAKE


def test_agent_pipeline_end_to_end_offline(tiny_scenario, monkeypatch):
    monkeypatch.setattr(system, "run_dispatch", fake_dispatch)
    monkeypatch.setattr(system, "run_hospital", fake_hospital)
    engine = Engine(tiny_scenario, AgentSystem(oracle=True))
    engine.run()
    assert engine.state.find_victim("V-01").status == VictimStatus.TREATED
    assert any(m["message_type"] == "commit" for m in engine.log.of_kind("agent_message"))
    executed = engine.log.of_kind("action_accepted")
    assert executed and all(e["message_id"] for e in executed)   # every action traces to a COMMIT
    assert not engine.log.of_kind("action_rejected")