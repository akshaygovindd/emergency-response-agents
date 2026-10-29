"""The story of a run for the replay player: agent messages and conflict negotiation chains.

Built from the event log alone. Python decides what each message means and how a conflict unfolded
(conflict -> counter-offer -> accepted/rejected -> executed); the player only displays it.

Message rows: {i, t, id, from, to, type, badge, text, why, inc, adm}
Conflict rows: {id, t, kind, text, incidents, resources, method, stages: [{key, label, ref, t, text}]}
"""
from __future__ import annotations

AGENT_LABELS = {"incident_assessment": "Assessment", "dispatch": "Dispatch", "resource_allocation": "Resource Alloc.",
                "hospital_coordination": "Hospital", "python": "System"}
BADGES = {"info": "INFO", "proposal": "PROPOSAL", "counter_proposal": "COUNTER", "accept": "ACCEPT",
          "reject": "REJECT", "commit": "COMMIT", "escalate": "ESCALATE"}
TYPE_KEYS = {"counter_proposal": "counter"}            # message type -> class key used by the player


def agent_label(name: str | None) -> str:
    return AGENT_LABELS.get(name or "", (name or "").replace("_", " ").title())


def resource_name(resource: str) -> str:
    """'ambulance:AMB-01' -> 'AMB-01', 'er:H-T' -> 'H-T ER'."""
    kind, _, name = resource.partition(":")
    return f"{name} ER" if kind == "er" else name or resource


def describe_action(action: dict | None, incident: str | None = None) -> str:
    """One short phrase for a proposed or executed action."""
    if not action:
        return f"assessed {incident}" if incident else ""
    kind = action["action_type"]
    victims = ", ".join(action.get("victim_ids") or [])
    if kind == "assign_ambulance":
        return f"{action['ambulance_id']} to {incident}" + (f" ({victims})" if victims else "")
    if kind == "assign_responder":
        return f"{action['responder_id']} to {incident}"
    if kind in ("admit_patient", "divert_patient"):
        verb = "admit" if kind == "admit_patient" else "divert"
        return f"{verb} {victims} to {action['hospital_id']}"
    return kind.replace("_", " ")


def feed_text(action: dict | None, incident: str | None = None, past: bool = False) -> str:
    """Plain-verb phrase for the feed: 'send AMB-01 to INC-01' (past tense: 'sent AMB-01 to INC-01')."""
    if not action:
        return f"assess {incident}" if incident else ""
    kind = action["action_type"]
    victims = ", ".join(action.get("victim_ids") or [])
    if kind in ("assign_ambulance", "assign_responder"):
        unit = action.get("ambulance_id") or action.get("responder_id")
        return f"{'sent' if past else 'send'} {unit} to {incident}" + (f" ({victims})" if victims else "")
    if kind in ("admit_patient", "divert_patient"):
        verb = ("admitted" if past else "admit") if kind == "admit_patient" else ("diverted" if past else "divert")
        return f"{verb} {victims} to {action['hospital_id']}"
    return kind.replace("_", " ")


def conflict_text(e: dict) -> str:
    """'INC-01 and INC-02 both want AMB-01' (falls back to the log's own reason)."""
    incidents = e["incident_ids"]
    if len(incidents) < 2:
        return e["reason"]
    names = ", ".join(incidents[:-1]) + f" and {incidents[-1]}"
    quantifier = "both" if len(incidents) == 2 else "all"
    return f"{names} {quantifier} want " + " / ".join(dict.fromkeys(resource_name(r) for r in e["resources"]))


# ───────── Feed ─────────
def feed_messages(events: list[dict]) -> list[dict]:
    """Every message the player shows, in log order (the player lists them newest first)."""
    rows = []
    for e in events:
        row = _message_row(e)
        if row:
            rows.append({"i": len(rows), **row})
    return rows


def _message_row(e: dict) -> dict | None:
    kind, t = e["kind"], e["t"]
    if kind == "agent_message":
        mtype = e["message_type"]
        negotiation = e.get("negotiation_id") or ""
        return {"t": t, "id": e["message_id"], "from": agent_label(e["sender"]), "to": agent_label(e["recipient"]),
                "type": TYPE_KEYS.get(mtype, mtype), "badge": BADGES.get(mtype, mtype.upper()),
                "text": feed_text(e.get("proposed_action"), e.get("incident_id")),
                "why": e.get("reason") or "", "inc": e.get("incident_id"), "adm": negotiation.startswith("ADM-")}
    if kind == "conflict_detected":
        return {"t": t, "id": e["conflict_id"], "from": "System", "to": "all agents", "type": "conflict",
                "badge": "CONFLICT", "text": conflict_text(e), "why": e["reason"],
                "inc": (e["incident_ids"] or [None])[0], "adm": False}
    if kind == "action_accepted":
        return {"t": t, "id": e["message_id"], "from": "System", "to": "", "type": "executed",
                "badge": "EXECUTED", "text": feed_text(e["action"], e["incident_id"], past=True),
                "why": f"checked and carried out ({e['source']})", "inc": e["incident_id"], "adm": False}
    return None


# ───────── Conflicts ─────────
def conflict_chains(events: list[dict]) -> list[dict]:
    """One row per detected conflict with the stages the strip draws."""
    messages = [e for e in events if e["kind"] == "agent_message"]
    resolved = {e["conflict_id"]: e for e in events if e["kind"] == "conflict_resolved"}
    accepted = [e for e in events if e["kind"] == "action_accepted"]
    chains = []
    for c in (e for e in events if e["kind"] == "conflict_detected"):
        mine = [m for m in messages if m.get("negotiation_id") == c["conflict_id"]]
        outcome = resolved.get(c["conflict_id"], {})
        counter = next((m for m in mine if m["message_type"] == "counter_proposal"), None)
        stages = [{"key": "conflict", "label": "Conflict", "ref": c["conflict_id"], "t": c["t"],
                   "text": conflict_text(c)}]
        stages.append(_counter_stage(counter, outcome))
        stages.append(_outcome_stage(counter, mine, outcome, c))
        stages.append(_executed_stage(counter, accepted, c))
        chains.append({"id": c["conflict_id"], "t": c["t"], "kind": c["conflict_type"], "text": conflict_text(c),
                       "incidents": c["incident_ids"], "resources": [r.partition(":")[2] or r for r in c["resources"]],
                       "method": outcome.get("method"), "stages": stages})
    return chains


def _counter_stage(counter: dict | None, outcome: dict) -> dict:
    if counter is None:
        how = "one claim granted outright" if outcome.get("method") == "negotiation" else "settled by rule"
        return {"key": "counter", "label": "Counter-offer", "ref": None, "t": None, "text": f"none ({how})"}
    text = f"{agent_label(counter['sender'])} offers {describe_action(counter['proposed_action'], counter['incident_id'])}"
    return {"key": "counter", "label": "Counter-offer", "ref": counter["message_id"], "t": counter["t"], "text": text}


def _outcome_stage(counter: dict | None, mine: list[dict], outcome: dict, conflict: dict) -> dict:
    reply = next((m for m in mine if counter and m.get("in_reply_to") == counter["message_id"]
                  and m["message_type"] in ("accept", "reject")), None)
    if reply is not None:
        label = "Accepted" if reply["message_type"] == "accept" else "Rejected"
        verb = "accepts" if reply["message_type"] == "accept" else "rejects"
        text = f"{agent_label(reply['sender'])} {verb} {describe_action(reply['proposed_action'], reply['incident_id'])}"
        return {"key": "outcome", "label": label, "ref": reply["message_id"], "t": reply["t"], "text": text}
    winner = next((m for m in mine if m["message_type"] == "accept" and m["sender"] == "resource_allocation"), None)
    method = (outcome.get("method") or "unresolved").replace("_", " ")
    text = (f"{winner['incident_id']} keeps its claim ({method})" if winner else f"settled by {method}")
    return {"key": "outcome", "label": "Resolved", "ref": winner["message_id"] if winner else conflict["conflict_id"],
            "t": conflict["t"], "text": text}


def _executed_stage(counter: dict | None, accepted: list[dict], conflict: dict) -> dict:
    """The validated action the negotiation led to: the counter-offer's, else one on the contested resource."""
    names = {r.partition(":")[2] for r in conflict["resources"]}
    same_minute = [a for a in accepted if a["t"] == conflict["t"]]

    def matches(a: dict) -> bool:
        act = a["action"]
        if counter is not None:
            want = counter["proposed_action"]
            return all(act.get(k) == want.get(k) for k in ("action_type", "ambulance_id", "responder_id", "hospital_id")) \
                and a["incident_id"] == counter["incident_id"]
        return a["incident_id"] in conflict["incident_ids"] and bool(
            names & {act.get("ambulance_id"), act.get("hospital_id"), act.get("responder_id")})

    hit = next((a for a in same_minute if matches(a)), None)
    if hit is None:
        return {"key": "executed", "label": "Executed", "ref": None, "t": None, "text": "no matching action"}
    return {"key": "executed", "label": "Executed", "ref": hit["message_id"], "t": hit["t"],
            "text": f"{describe_action(hit['action'], hit['incident_id'])} validated"}
