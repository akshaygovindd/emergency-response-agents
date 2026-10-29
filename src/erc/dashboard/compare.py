"""Compare two systems on the same scenario and seed: where do their decisions first differ?

Both runs start from the same world, so until they make a different decision they are the same story.
The first minute whose set of accepted actions differs is the "first difference"; each side's actions
there are described in plain words. Built from the event logs only.
"""
from __future__ import annotations

from erc.dashboard.story import feed_text

SYSTEM_NAMES = {"naive": "Naive", "greedy": "Greedy", "agents": "Agents (no negotiation)",
                "negotiation": "Negotiation", "oracle": "Oracle"}


def _decisions(events: list[dict]) -> dict[int, dict[tuple, str]]:
    """minute -> {decision key: plain-words description} for every accepted action."""
    out: dict[int, dict[tuple, str]] = {}
    for e in events:
        if e["kind"] != "action_accepted":
            continue
        act = e["action"]
        target = act.get("ambulance_id") or act.get("responder_id") or act.get("hospital_id")
        key = (e["incident_id"], act["action_type"], target, tuple(sorted(act.get("victim_ids") or [])))
        out.setdefault(e["t"], {})[key] = feed_text(act, e["incident_id"], past=True)
    return out


def first_difference(events_a: list[dict], events_b: list[dict], name_a: str, name_b: str) -> dict | None:
    """{t, a: [what A did], b: [what B did], text} for the first minute the two runs decide differently."""
    a, b = _decisions(events_a), _decisions(events_b)
    for t in sorted(set(a) | set(b)):
        only_a = [text for key, text in a.get(t, {}).items() if key not in b.get(t, {})]
        only_b = [text for key, text in b.get(t, {}).items() if key not in a.get(t, {})]
        if only_a or only_b:
            say = lambda name, acts: f"{name} {'; '.join(acts)}" if acts else f"{name} made no different decision"
            return {"t": t, "a": only_a, "b": only_b,
                    "text": f"First difference at minute {t}: {say(name_a, only_a)}. {say(name_b, only_b)}."}
    return None
