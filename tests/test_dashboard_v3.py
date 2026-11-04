"""Tests: dashboard support for v3 staff loans, built from the saved v3 logs (no simulation, no API calls)."""
import json

import pytest

from erc.dashboard import results_view as rv
from erc.dashboard.catalog import run_catalog
from erc.dashboard.export import export_replay, loan_summary, loans_at
from erc.dashboard.feed import to_feed_item
from erc.dashboard.negotiations import is_notable, negotiation_records
from erc.dashboard.replay import LOGS_DIR, available_runs
from erc.dashboard.story import agent_label, feed_messages, feed_text, plain_text
from erc.dashboard.timeline import timeline_items

PATH = LOGS_DIR / "v3" / "negotiation" / "surge_seed42_negotiation.jsonl"


@pytest.fixture(scope="module")
def events():
    return [json.loads(line) for line in PATH.read_text().splitlines() if line]


def test_v3_is_in_the_run_catalog():
    cat = run_catalog(available_runs())
    assert "v3" in cat and set(cat["v3"]) == {"surge", "bottleneck"}
    assert cat["v3"]["surge"]["1"] == ["naive", "greedy", "agents", "negotiation"]


def test_hospital_instances_get_readable_labels():
    assert agent_label("hospital_coordination:H-T") == "Hospital H-T"
    assert agent_label("hospital_coordination") == "Hospital"
    assert plain_text(agent_label("hospital_coordination:H-G")) == "Hospital General Hospital"


def test_loan_wording():
    action = {"action_type": "loan_staff", "loan": {"lender_id": "H-G", "borrower_id": "H-T", "capability": "general",
                                                    "teams": 1, "duration_min": 20, "serves": []}}
    assert feed_text(action) == "lend 1 general team H-G → H-T for 20 min"
    assert feed_text(action, past=True).startswith("lent 1 general team")
    e = {"kind": "loan_started", "t": 23, "loan_id": "L-01", "lender_id": "H-G", "borrower_id": "H-T", "capability": "general",
         "teams": 1, "staff_ids": [], "arrive_min": 37, "ends_min": 57}
    assert "arrives minute 37" in to_feed_item(e).text


def test_feed_rows_and_timeline_show_the_loan_chain(events):
    rows = feed_messages(events)
    loan_rows = [r for r in rows if r.get("loan")]
    assert {"request", "accept", "loan"} <= {r["type"] for r in loan_rows}
    assert any(r["from"] == "Hospital H-T" and r["to"] == "Hospital H-G" and r["type"] == "request" for r in loan_rows)
    sentences = [i["text"] for i in timeline_items(rows)]
    assert any(s.startswith("Asked for staff") for s in sentences) and any(s.startswith("Agreed") for s in sentences)
    assert any("lent 1 general team" in s.lower() for s in sentences)                    # the executed line
    assert any("arrived at Trauma Center" in s for s in sentences)                         # staff arrival


def test_negotiation_records_include_loans_with_every_step(events):
    loans = [r for r in negotiation_records(events) if r["kind"] == "loan"]
    assert len(loans) == 2 and loans[0]["id"] == "LN-t023-01"
    first = loans[0]
    assert [s["key"] for s in first["steps"]] == ["request", "accept", "resolved"] and first["outcome"] == "Lent as requested"
    assert first["steps"][0]["raw"]["sender_id"] == "hospital_coordination:H-T"
    assert not is_notable(first)


def test_refused_loans_are_shown_with_the_validator_reason():
    path = LOGS_DIR / "v3" / "negotiation" / "surge_seed48_negotiation.jsonl"
    records = negotiation_records([json.loads(line) for line in path.read_text().splitlines() if line])
    refused = [r for r in records if r["kind"] == "loan" and r["outcome"].startswith("Refused")]
    assert refused and refused[0]["steps"][-1]["label"] == "Validator refused" and is_notable(refused[0])
    outcome_step = next(st for st in refused[0]["steps"] if st["key"] == "resolved")
    assert outcome_step["why"] == refused[0]["outcome"] and "Lent" not in outcome_step["why"]      # the stepper outcome is the refusal


def test_replay_bundle_has_loans_and_slot_counts(events):
    b = export_replay("v3", "surge", 42, "negotiation")
    assert [ln["id"] for ln in b["loans"]] == ["L-01", "L-02"] and b["loans"][0]["t_arrive"] == 37
    frame = b["frames"][45]
    assert frame["l"][0][:5] == ["H-G", "H-T", "general", 1, "active"]
    assert [h[4] for h in frame["h"]] == [5, 4, 3]                              # H-T +1, H-B has not gained yet, H-G -2 slots
    assert "l" not in b["frames"][10]
    assert loan_summary(events)[0]["staff"] == ["D-05", "N-09"] and loans_at({}) == []


def test_old_versions_export_without_loan_fields():
    b = export_replay("v2", "surge", 42, "negotiation")
    assert b["loans"] == [] and all("l" not in f for f in b["frames"])


def test_results_page_has_v3():
    assert "v3" in rv.FRAMES
    p = rv.results_payload("v3")
    assert p["runs"] == 60 and {r["scenario"] for r in p["csr"]} == {"surge", "bottleneck"}
    assert p["oracle"] == [] and "no oracle runs in v3" in p["takeaways"]["oracle"]
    assert p["v3"]["takeaway"].startswith("(v3) Staff sharing") and "v3" not in rv.results_payload("v2")
    assert {r["metric_name"] for r in p["v3"]["contrasts"]} == {"P1", "P2", "never_started", "CSR"}
