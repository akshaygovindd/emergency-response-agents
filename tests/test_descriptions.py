"""Tests: report facts must be complete, and missing caches must be handled (no API calls)."""
from erc.config import ScenarioName
from erc.scenarios.descriptions import incident_facts, load_descriptions


def test_facts_cover_every_victim_and_scene_need(tiny_scenario):
    fire = tiny_scenario.incidents[1]                 # building fire with one victim
    facts = incident_facts(fire)
    assert "Number of injured people: 1" in facts
    assert "fire or hazard is still active" in facts.lower()
    assert facts.count(" person: ") == fire.victim_count


def test_missing_cache_returns_empty():
    assert load_descriptions(ScenarioName.NORMAL, 999) == {}