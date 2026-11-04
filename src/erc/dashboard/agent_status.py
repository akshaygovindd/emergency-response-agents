"""Agent status panel for the replay player: what each of the four agents is doing, minute by minute.

Everything is derived from the run log (no simulation, no API calls). Per agent and minute:
  status   "negotiating" if it sent or received a message that belongs to a negotiation (conflict or admission)
           during that minute, "working" if it sent any other message, otherwise "idle"
  last     its latest message so far, in plain words, with the minute it was sent
  pending  (label, count) pairs of requests still open at the end of that minute
Rule-based systems (naive, greedy) have no agents, so the panel is flagged inactive.
"""
from __future__ import annotations

from erc.dashboard.story import plain_text

AGENTS = (("incident_assessment", "Assessment"), ("dispatch", "Dispatch"),
          ("hospital_coordination", "Hospital Coordination"), ("resource_allocation", "Resource Allocation"))
IDLE, WORKING, NEGOTIATING = "idle", "working", "negotiating"


def _action_key(m: dict) -> tuple:
    a = m.get("proposed_action") or {}
    return (m.get("incident_id"), a.get("action_type"), a.get("ambulance_id"), a.get("responder_id"),
            a.get("hospital_id"), tuple(a.get("victim_ids") or ()))


def _last_text(m: dict) -> str:
    """'Proposed to send Ambulance 1 to Incident 2' for a logged agent message."""
    from erc.dashboard.story import feed_text
    kind, body = m["message_type"], plain_text(feed_text(m.get("proposed_action"), m.get("incident_id")))
    short = body.removeprefix("send ")
    return {"info": "Assessed " + body.removeprefix("assess "), "proposal": f"Proposed to {body}",
            "counter_proposal": f"Suggested instead: {short}", "accept": f"Accepted: {short}",
            "reject": f"Declined: {short}", "commit": f"Committed: {short}",
            "escalate": f"Escalated: {short}"}.get(kind, body)


def has_agents(events: list[dict]) -> bool:
    return any(e["kind"] == "agent_message" for e in events)


def agent_status_by_minute(events: list[dict], scenario: dict, promised: list[dict[str, int]],
                           last_minute: int) -> list[list[dict]]:
    """frames[t] -> one dict per agent: {status, last, last_t, pending: [[label, n]]}."""
    msgs = [e for e in events if e["kind"] == "agent_message"]
    arrivals = {e["incident_id"]: e["t"] for e in events if e["kind"] == "incident_arrived"}
    assessed = {m["incident_id"]: m["t"] for m in msgs if m["message_type"] == "info"}
    dispatched = {}
    for e in events:
        if e["kind"] == "action_accepted" and e["action"]["action_type"].startswith("assign_"):
            dispatched.setdefault(e["incident_id"], e["t"])
    resolutions: dict[tuple, int] = {}               # action -> first minute a verdict on it was sent
    for m in msgs:
        if m["message_type"] in ("accept", "reject", "commit", "counter_proposal"):
            resolutions.setdefault(_action_key(m), m["t"])
    conflicts = [(e["t"], e["conflict_id"]) for e in events if e["kind"] == "conflict_detected"]
    closed = {e["conflict_id"]: e["t"] for e in events if e["kind"] == "conflict_resolved"}

    by_minute: dict[int, list[dict]] = {}
    for m in msgs:
        by_minute.setdefault(m["t"], []).append(m)
    latest: dict[str, dict] = {}
    out = []
    for t in range(last_minute + 1):
        here = by_minute.get(t, [])
        for m in here:
            latest[m["sender"]] = m
        frame = []
        for key, label in AGENTS:
            mine = [m for m in here if m["sender"] == key or m["recipient"] == key]
            negotiating = any(m.get("negotiation_id") for m in mine)
            working = any(m["sender"] == key for m in here)
            status = NEGOTIATING if negotiating else WORKING if working else IDLE
            lm = latest.get(key)
            frame.append({"status": status, "last": _last_text(lm) if lm else None, "last_t": lm["t"] if lm else None,
                          "pending": _pending(key, t, msgs, arrivals, assessed, dispatched, resolutions,
                                              conflicts, closed, promised)})
        out.append(frame)
    return out


def _pending(key, t, msgs, arrivals, assessed, dispatched, resolutions, conflicts, closed, promised) -> list[list]:
    open_proposals = lambda recipient, adm: sum(                      # noqa: E731
        1 for m in msgs if m["t"] <= t and m["message_type"] == "proposal" and m["recipient"] == recipient
        and (m.get("negotiation_id") or "").startswith("ADM-") == adm
        and resolutions.get(_action_key(m), 10 ** 9) > t)
    arrived = [i for i, at in arrivals.items() if at <= t]
    if key == "incident_assessment":
        return [["reports not yet assessed", sum(assessed.get(i, 10 ** 9) > t for i in arrived)]]
    if key == "dispatch":
        return [["incidents awaiting a unit", sum(dispatched.get(i, 10 ** 9) > t for i in arrived)]]
    if key == "hospital_coordination":
        return [["admission requests unanswered", open_proposals("hospital_coordination", True)],
                ["patients promised, not yet arrived", sum(promised[t].values())]]
    return [["proposals awaiting a decision", open_proposals("resource_allocation", False)],
            ["conflicts open", sum(1 for ct, cid in conflicts if ct <= t and closed.get(cid, 10 ** 9) > t)]]
