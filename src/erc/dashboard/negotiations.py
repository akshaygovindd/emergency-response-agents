"""Negotiation explorer data: every conflict and every hospital admission negotiation of one run.

Built from the event log. A record is one negotiation: when it happened, what kind, which incidents and
units were involved, each step in order (with the raw structured log message behind it) and the outcome.

Record: {id, kind: conflict | admission, t, type, incidents, units, steps, outcome, rounds}
Step:   {key, label, t, id, from, to, text, why, raw}
"""
from __future__ import annotations

from erc.dashboard.story import agent_label, conflict_text, feed_text, resource_name

STEP_LABELS = {"proposal": "Proposal", "counter_proposal": "Counter-offer", "accept": "Accept", "reject": "Reject",
               "escalate": "Arbitration", "info": "Info", "commit": "Commit"}
STEP_KEYS = {"counter_proposal": "counter"}
CONFLICT_TYPES = {"resource": "Resource conflict", "capacity": "Capacity conflict", "routing": "Routing conflict"}
ADMISSION_OUTCOMES = {"accepted": "Accepted as proposed", "revised": "Revised after the hospital's counter",
                      "arbitrated": "Arbitrated by Resource Allocation", "pending": "Pending (no hospital could take them yet)",
                      "fallback": "Settled by fallback rule"}
CONFLICT_OUTCOMES = {"negotiation": "Settled by negotiation", "priority_rule": "Settled by the fixed priority rule",
                     "fallback": "Settled by fallback rule"}


def negotiation_records(events: list[dict]) -> list[dict]:
    """Conflicts and admission negotiations of one run, in order of time."""
    messages: dict[str, list[dict]] = {}
    for e in events:
        if e["kind"] == "agent_message" and e.get("negotiation_id"):
            messages.setdefault(e["negotiation_id"], []).append(e)
    resolved = {e["conflict_id"]: e for e in events if e["kind"] == "conflict_resolved"}
    records = [_conflict_record(c, messages.get(c["conflict_id"], []), resolved.get(c["conflict_id"]))
               for c in events if c["kind"] == "conflict_detected"]
    records += [_admission_record(e, messages.get(e["negotiation_id"], []))
                for e in events if e["kind"] == "admission_resolved"]
    return sorted(records, key=lambda r: (r["t"], r["id"]))


def _message_step(m: dict) -> dict:
    mtype = m["message_type"]
    return {"key": STEP_KEYS.get(mtype, mtype), "label": STEP_LABELS.get(mtype, mtype.title()), "t": m["t"],
            "id": m["message_id"], "from": agent_label(m["sender"]), "to": agent_label(m["recipient"]),
            "text": feed_text(m.get("proposed_action"), m.get("incident_id")), "why": m.get("reason") or "", "raw": m}


def _conflict_record(c: dict, messages: list[dict], outcome: dict | None) -> dict:
    steps = [{"key": "conflict", "label": "Conflict detected", "t": c["t"], "id": c["conflict_id"], "from": "System",
              "to": "all agents", "text": conflict_text(c), "why": c["reason"], "raw": c}]
    steps += [_message_step(m) for m in messages]
    method = (outcome or {}).get("method")
    if outcome:
        kept, dropped = outcome.get("winners", []), outcome.get("losers", [])
        steps.append({"key": "fallback" if method == "fallback" else "resolved",
                      "label": {"fallback": "Fallback", "priority_rule": "Rule"}.get(method, "Resolved"),
                      "t": outcome.get("t", c["t"]), "id": c["conflict_id"], "from": "System", "to": "",
                      "text": f"kept {', '.join(kept) or 'none'}; dropped {', '.join(dropped) or 'none'}",
                      "why": CONFLICT_OUTCOMES.get(method, str(method)), "raw": outcome})
    rounds = max((m.get("round") or 0 for m in messages), default=0)
    return {"id": c["conflict_id"], "kind": "conflict", "t": c["t"], "type": CONFLICT_TYPES.get(c["conflict_type"], c["conflict_type"]),
            "incidents": c["incident_ids"], "units": [resource_name(r) for r in c["resources"]], "steps": steps,
            "outcome": CONFLICT_OUTCOMES.get(method, "Unresolved"), "method": method, "rounds": rounds}


def _admission_record(done: dict, messages: list[dict]) -> dict:
    steps = [_message_step(m) for m in messages]
    method = done["method"]
    went = done["hospital_id"] or "no hospital yet"
    steps.append({"key": "resolved", "label": "Outcome", "t": done["t"], "id": done["negotiation_id"], "from": "System", "to": "",
                  "text": f"{', '.join(done['victim_ids'])} to {went} (requested {done['requested']})",
                  "why": ADMISSION_OUTCOMES.get(method, method), "raw": done})
    first = messages[0]["t"] if messages else done["t"]
    return {"id": done["negotiation_id"], "kind": "admission", "t": first, "type": "Hospital admission",
            "incidents": [done["incident_id"]], "units": [done["requested"]] + ([done["hospital_id"]] if done["hospital_id"] not in (None, done["requested"]) else []),
            "steps": steps, "outcome": ADMISSION_OUTCOMES.get(method, method), "method": method, "rounds": done["rounds"]}


def is_notable(record: dict) -> bool:
    """A negotiation where something other than the first proposal happened (counter, rejection, arbitration, fallback)."""
    if record["kind"] == "admission":
        return record["method"] != "accepted"
    return record["method"] in ("negotiation", "fallback") or any(s["key"] in ("counter", "reject") for s in record["steps"])
