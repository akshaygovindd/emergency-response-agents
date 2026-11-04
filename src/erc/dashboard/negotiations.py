"""Negotiation explorer data: every conflict and every hospital admission negotiation of one run.

Built from the event log. A record is one negotiation: when it happened, what kind, which incidents and
units were involved, each step in order (with the raw structured log message behind it) and the outcome.

Record: {id, kind: conflict | admission, t, type, incidents, units, steps, outcome, rounds}
Step:   {key, label, t, id, from, to, text, why, raw}
"""
from __future__ import annotations

from erc.dashboard.story import agent_label, conflict_text, feed_text, plain_text, resource_name

STEP_LABELS = {"request": "Loan request", "proposal": "Proposal", "counter_proposal": "Counter-offer", "accept": "Accept", "reject": "Reject",
               "escalate": "Arbitration", "info": "Info", "commit": "Commit"}
STEP_KEYS = {"counter_proposal": "counter"}
CONFLICT_TYPES = {"resource": "Resource conflict", "capacity": "Capacity conflict", "routing": "Routing conflict"}
ADMISSION_OUTCOMES = {"accepted": "Accepted as proposed", "revised": "Revised after the hospital's counter",
                      "arbitrated": "Arbitrated by Resource Allocation", "pending": "Pending (no hospital could take them yet)",
                      "fallback": "Settled by fallback rule"}
LOAN_OUTCOMES = {"accepted": "Lent as requested", "counter_accepted": "Lent on the lender's counter-offer", "revised": "Lent after a new request",
                 "redirect": "Lent by another hospital (rule)", "arbitrated": "Arbitrated by Resource Allocation",
                 "fallback": "Settled by fallback rule", "pending": "No loan (no hospital could spare the staff)"}
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
    refused = [e for e in events if e["kind"] == "action_rejected" and e["action"]["action_type"] == "loan_staff"]
    records += [_loan_record(e, messages.get(e["negotiation_id"], []), refused)
                for e in events if e["kind"] == "loan_resolved"]
    return sorted(records, key=lambda r: (r["t"], r["id"]))


def _message_step(m: dict) -> dict:
    mtype = m["message_type"]
    return {"key": STEP_KEYS.get(mtype, mtype), "label": STEP_LABELS.get(mtype, mtype.title()), "t": m["t"],
            "id": m["message_id"], "from": plain_text(agent_label(m.get("sender_id", m["sender"]))),
            "to": plain_text(agent_label(m.get("recipient_id", m["recipient"]))),
            "text": feed_text(m.get("proposed_action"), m.get("incident_id")), "why": m.get("reason") or "", "raw": m,
            "plain": plain_text(feed_text(m.get("proposed_action"), m.get("incident_id")))}


def _conflict_record(c: dict, messages: list[dict], outcome: dict | None) -> dict:
    steps = [{"key": "conflict", "label": "Conflict detected", "t": c["t"], "id": c["conflict_id"], "from": "System",
              "to": "all agents", "text": conflict_text(c), "why": c["reason"], "raw": c, "plain": plain_text(conflict_text(c))}]
    steps += [_message_step(m) for m in messages]
    method = (outcome or {}).get("method")
    if outcome:
        kept, dropped = outcome.get("winners", []), outcome.get("losers", [])
        steps.append({"key": "fallback" if method == "fallback" else "resolved",
                      "label": {"fallback": "Fallback", "priority_rule": "Rule"}.get(method, "Resolved"),
                      "t": outcome.get("t", c["t"]), "id": c["conflict_id"], "from": "System", "to": "",
                      "plain": f"Kept {len(kept)} proposal{'s' if len(kept) != 1 else ''}, dropped {len(dropped)}",
                      "text": f"kept {', '.join(kept) or 'none'}; dropped {', '.join(dropped) or 'none'}",
                      "why": CONFLICT_OUTCOMES.get(method, str(method)), "raw": outcome})
    rounds = max((m.get("round") or 0 for m in messages), default=0)
    return {"id": c["conflict_id"], "kind": "conflict", "t": c["t"], "type": CONFLICT_TYPES.get(c["conflict_type"], c["conflict_type"]),
            "incidents": c["incident_ids"], "units": [resource_name(r) for r in c["resources"]], "steps": steps,
            "incidents_plain": [plain_text(i) for i in c["incident_ids"]], "units_plain": [plain_text(resource_name(r)) for r in c["resources"]],
            "outcome": CONFLICT_OUTCOMES.get(method, "Unresolved"), "method": method, "rounds": rounds}


def _admission_record(done: dict, messages: list[dict]) -> dict:
    steps = [_message_step(m) for m in messages]
    method = done["method"]
    went = done["hospital_id"] or "no hospital yet"
    steps.append({"key": "resolved", "label": "Outcome", "t": done["t"], "id": done["negotiation_id"], "from": "System", "to": "",
                  "text": f"{', '.join(done['victim_ids'])} to {went} (requested {done['requested']})",
                  "plain": plain_text(f"{len(done['victim_ids'])} patient{'s' if len(done['victim_ids']) != 1 else ''} to {went} (requested {done['requested']})"),
                  "why": ADMISSION_OUTCOMES.get(method, method), "raw": done})
    first = messages[0]["t"] if messages else done["t"]
    return {"id": done["negotiation_id"], "kind": "admission", "t": first, "type": "Hospital admission",
            "incidents": [done["incident_id"]], "units": [done["requested"]] + ([done["hospital_id"]] if done["hospital_id"] not in (None, done["requested"]) else []),
            "incidents_plain": [plain_text(done["incident_id"])],
            "units_plain": [plain_text(u) for u in [done["requested"]] + ([done["hospital_id"]] if done["hospital_id"] not in (None, done["requested"]) else [])],
            "steps": steps, "outcome": ADMISSION_OUTCOMES.get(method, method), "method": method, "rounds": done["rounds"]}


def _loan_record(done: dict, messages: list[dict], refused: list[dict]) -> dict:
    """A staff-loan negotiation (v3): request, the lender's answer, any counter or arbitration, and what the validator did."""
    steps = [_message_step(m) for m in messages]
    method = done["method"]
    if done["lender_id"]:
        said = (f"{done['lender_id']} lends {done['teams']} {done['capability']} team{'s' if done['teams'] != 1 else ''} to "
                f"{done['borrower_id']} for {done['duration_min']} min")
    else:
        said = f"{done['borrower_id']} gets no {done['capability']} loan"
    steps.append({"key": "resolved", "label": "Outcome", "t": done["t"], "id": done["negotiation_id"], "from": "System", "to": "",
                  "text": said, "plain": plain_text(said), "why": LOAN_OUTCOMES.get(method, method), "raw": done})
    blocked = next((e for e in refused if e["t"] == done["t"] and e["action"]["loan"]["borrower_id"] == done["borrower_id"]
                    and e["action"]["loan"]["lender_id"] == done["lender_id"]), None)
    outcome = LOAN_OUTCOMES.get(method, method)
    if blocked:
        steps.append({"key": "fallback", "label": "Validator refused", "t": blocked["t"], "id": blocked["message_id"] or "", "from": "System", "to": "",
                      "text": blocked["detail"], "plain": plain_text(blocked["detail"]), "why": blocked["reason"], "raw": blocked})
        outcome = "Refused when carried out: " + blocked["reason"].replace("_", " ")
    first = messages[0]["t"] if messages else done["t"]
    incident = messages[0]["incident_id"] if messages else ""
    places = [done["requested"], done["borrower_id"]] + ([done["lender_id"]] if done["lender_id"] not in (None, done["requested"]) else [])
    return {"id": done["negotiation_id"], "kind": "loan", "t": first, "type": "Staff loan", "incidents": [incident],
            "incidents_plain": [plain_text(incident)], "units": places, "units_plain": [plain_text(u) for u in places],
            "steps": steps, "outcome": outcome, "method": method, "rounds": done["rounds"]}


def is_notable(record: dict) -> bool:
    """A negotiation where something other than the first proposal happened (counter, rejection, arbitration, fallback)."""
    if record["kind"] in ("admission", "loan"):
        return record["method"] != "accepted" or any(s["key"] in ("counter", "reject", "fallback") for s in record["steps"])
    return record["method"] in ("negotiation", "fallback") or any(s["key"] in ("counter", "reject") for s in record["steps"])
