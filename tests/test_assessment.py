"""Tests: assessment conversion, oracle, and scoring must be correct (no API calls)."""
from erc.agents.assessment import (
    ASSESSMENT_AGENT, AssessmentOutput, VictimFinding, oracle_assessment, score, to_report,
)
from erc.agents.llm_cache import cache_key


def test_oracle_is_perfect(tiny_scenario):
    for inc in tiny_scenario.incidents:
        s = score(inc, oracle_assessment(inc))
        assert s["severity_exact"] == s["capability_correct"] == s["als_correct"] == s["victims_true"]
        assert s["responder_correct"] == 1 and s["count_correct"] == 1


def test_to_report_maps_ids_and_clamps(tiny_scenario):
    inc = tiny_scenario.incidents[0]
    out = AssessmentOutput(victims=[VictimFinding(position=1, severity=9, care_type="trauma",
                                                  needs_advanced_life_support=True)],
                           team_needed="none", priority_score=150, reasoning="test")
    r = to_report(inc, out)
    assert r.victims[0].victim_id == "V-01"
    assert int(r.victims[0].severity) == 5 and r.priority_score == 100 and r.required_responder is None


def test_score_counts_mistakes(tiny_scenario):
    inc = tiny_scenario.incidents[1]            # fire, one serious victim needing general care
    out = AssessmentOutput(victims=[VictimFinding(position=1, severity=4, care_type="burn",
                                                  needs_advanced_life_support=True)],
                           team_needed="none", priority_score=50, reasoning="test")
    s = score(inc, to_report(inc, out))
    assert s["severity_exact"] == 0 and s["severity_within1"] == 1
    assert s["capability_correct"] == 0 and s["als_correct"] == 0 and s["responder_correct"] == 0


def test_cache_key_depends_on_prompt():
    assert cache_key(ASSESSMENT_AGENT, "a") == cache_key(ASSESSMENT_AGENT, "a") != cache_key(ASSESSMENT_AGENT, "b")