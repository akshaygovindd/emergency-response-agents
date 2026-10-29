"""Tour moments for the replay player: a few bookmarked minutes of one run, each with a one-line caption.

Built from the event log and the story rows (see story.py); the player only jumps to them. A moment that
a run never had (no conflict in a greedy run, no admission negotiation in v1) is simply left out.

Moment rows: {t, title, caption}
"""
from __future__ import annotations

from erc.dashboard.story import plain_text



def tour_moments(events: list[dict], conflicts: list[dict], last_minute: int, final_kpis: dict,
                 critical_total: int) -> list[dict]:
    moments = [m for m in (_first_incident(events), _first_assessment(events), _first_conflict(conflicts),
                           _counter_and_accept(conflicts), _admission_decision(events)) if m]
    moments.append(_final_outcome(last_minute, final_kpis, critical_total, conflicts))
    return sorted(moments, key=lambda m: (m["t"], 0 if m["title"] != "Final outcome" else 1))


def _first_incident(events: list[dict]) -> dict | None:
    e = next((e for e in events if e["kind"] == "incident_arrived"), None)
    if e is None:
        return None
    n = e["victims"]
    return {"t": e["t"], "title": "First incident",
            "caption": f"{plain_text(e['incident_id'])} is reported with {n} patient{'s' if n != 1 else ''}; the clock has just started for them."}


def _first_assessment(events: list[dict]) -> dict | None:
    e = next((e for e in events if e["kind"] == "assessment"), None)
    msg = next((m for m in events if m["kind"] == "agent_message" and m["sender"] == "incident_assessment"
                and m.get("incident_id") == (e or {}).get("incident_id")), None)
    if e is None or msg is None:
        return None
    return {"t": e["t"], "title": "First assessment",
            "caption": f"The Assessment agent reads the 911 report for {plain_text(e['incident_id'])} and rates its priority {msg['priority']}."}


def _first_conflict(conflicts: list[dict]) -> dict | None:
    if not conflicts:
        return None
    c = conflicts[0]
    return {"t": c["t"], "title": "First conflict", "caption": f"The system detects it: {c['plain']}."}


def _counter_and_accept(conflicts: list[dict]) -> dict | None:
    for c in conflicts:
        counter, outcome = c["stages"][1], c["stages"][2]
        if counter["ref"] is not None and outcome["label"] in ("Accepted", "Rejected"):
            replier, verb = outcome["text"].split(" accepts " if outcome["label"] == "Accepted" else " rejects ")[0], \
                "accepts" if outcome["label"] == "Accepted" else "rejects"
            return {"t": outcome["t"], "title": f"Counter-offer {outcome['label'].lower()}",
                    "caption": f"{plain_text(counter['text'])}; {replier} {verb} it."}
    return None


def _admission_decision(events: list[dict]) -> dict | None:
    """v2 only: the first hospital decision that changed where patients went, else the first one at all."""
    resolved = [e for e in events if e["kind"] == "admission_resolved"]
    pick = next((e for e in resolved if e["method"] in ("revised", "arbitrated")), None) \
        or next((e for e in resolved if e["method"] == "accepted"), None)
    if pick is None:
        return None
    where, victims = pick.get("hospital_id"), ", ".join(pick["victim_ids"])
    if pick["method"] == "accepted":
        text = plain_text(f"{pick['hospital_id']} accepts the admission of {victims}.")
    else:
        text = plain_text(f"{pick['requested']} could not take {victims}; after {pick['rounds']} round"
                          f"{'s' if pick['rounds'] != 1 else ''} the {pick['method']} outcome sends them to {where}.")
    return {"t": pick["t"], "title": "Hospital admission decision", "caption": text}


def _final_outcome(last: int, k: dict, critical_total: int, conflicts: list[dict]) -> dict:
    text = f"{k['crit_ok']} of {critical_total} critical victims reached in time, {k['reached']} of {k['arrived']} victims reached"
    if conflicts:
        text += f"; {k['conflicts']} conflicts, {k['negotiated']} settled by negotiation"
    return {"t": last, "title": "Final outcome", "caption": text + "."}
