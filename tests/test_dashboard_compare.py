"""Tests: first-difference note and the compare page renderer."""
import json

import pytest

from erc.dashboard.compare import first_difference
from erc.dashboard.export import export_replay
from erc.dashboard.player import render_compare
from erc.dashboard.replay import LOGS_DIR


def accepted(t, incident, ambulance, victims=("V-1",)):
    return {"t": t, "kind": "action_accepted", "incident_id": incident, "source": "dispatch", "message_id": "m",
            "action": {"action_type": "assign_ambulance", "ambulance_id": ambulance, "victim_ids": list(victims)}}


def test_identical_runs_have_no_difference():
    run = [accepted(3, "INC-01", "AMB-01"), accepted(6, "INC-02", "AMB-02")]
    assert first_difference(run, list(run), "A", "B") is None


def test_first_difference_is_the_first_minute_the_decisions_differ():
    a = [accepted(3, "INC-01", "AMB-01"), accepted(6, "INC-02", "AMB-02")]
    b = [accepted(3, "INC-01", "AMB-01"), accepted(6, "INC-02", "AMB-05")]
    diff = first_difference(a, b, "Greedy", "Negotiation")
    assert diff["t"] == 6
    assert diff["a"] == ["sent AMB-02 to INC-02 (V-1)"] and diff["b"] == ["sent AMB-05 to INC-02 (V-1)"]
    assert "minute 6" in diff["text"] and "Greedy sent AMB-02" in diff["text"] and "Negotiation sent AMB-05" in diff["text"]


def test_one_side_doing_nothing_is_stated():
    diff = first_difference([accepted(4, "INC-01", "AMB-01")], [], "A", "B")
    assert diff["t"] == 4 and diff["b"] == [] and "B made no different decision" in diff["text"]


def test_real_runs_diverge_at_a_minute_with_a_conflict_or_a_different_choice():
    def load(mode):
        path = LOGS_DIR / "v1" / mode / f"normal_seed42_{mode}.jsonl"
        if not path.exists():
            pytest.skip("saved v1 run not available")
        return [json.loads(line) for line in path.read_text().splitlines() if line]
    diff = first_difference(load("greedy"), load("negotiation"), "Greedy", "Negotiation")
    assert diff is not None and diff["t"] >= 0 and diff["a"] and diff["b"]


def test_render_compare_embeds_two_players_and_no_placeholders():
    if not (LOGS_DIR / "v1" / "greedy" / "normal_seed42_greedy.jsonl").exists():
        pytest.skip("saved v1 run not available")
    sides = [{"label": m, "bundle": export_replay("v1", "normal", 42, m)} for m in ("greedy", "negotiation")]
    html = render_compare(sides[0], sides[1], {"t": 6, "a": [], "b": [], "text": "First difference at minute 6: x."})
    assert "__DATA__" not in html and "/*__" not in html
    data = json.loads(html.split('id="data">')[1].split("</script>")[0].replace("<\\/", "</"))
    assert data["a"]["label"] == "greedy" and data["diff"]["t"] == 6
    assert 'class="embed"' in data["a"]["html"] and 'class="embed"' in data["b"]["html"]
