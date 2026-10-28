"""Event feed for the replay dashboard.

Each raw log event kind can register a formatter that turns it into a FeedItem. Kinds without
a formatter are simply not shown, so new event types (e.g. hospital accept/reject/counter in
v2) only need one more `@feed_event(...)` function; nothing else has to change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# category -> icon; the app uses the categories for filtering
CATEGORIES = {
    "agent": "💬",
    "conflict": "⚠️",
    "action": "✅",
    "incident": "🚨",
    "movement": "🚑",
    "hospital": "🏥",
}


@dataclass(frozen=True)
class FeedItem:
    t: int
    category: str
    text: str

    @property
    def icon(self) -> str:
        return CATEGORIES.get(self.category, "•")


Formatter = Callable[[dict], "str | tuple[str, str] | None"]
_REGISTRY: dict[str, tuple[str, Formatter]] = {}


def feed_event(kind: str, category: str) -> Callable[[Formatter], Formatter]:
    """Register a formatter: returns the feed text for an event (None to hide it)."""
    def register(fn: Formatter) -> Formatter:
        _REGISTRY[kind] = (category, fn)
        return fn
    return register


def to_feed_item(event: dict) -> FeedItem | None:
    entry = _REGISTRY.get(event.get("kind", ""))
    if entry is None:
        return None
    category, fn = entry
    text = fn(event)
    return FeedItem(event["t"], category, text) if text else None


def feed_items(events: list[dict]) -> list[FeedItem]:
    """Feed items for the given events, newest first (stable within a minute)."""
    items = [i for e in events if (i := to_feed_item(e)) is not None]
    return list(reversed(items))


# ───────── Formatters ─────────
def _action_text(action: dict | None) -> str:
    if not action:
        return ""
    parts = [action["action_type"].replace("_", " ")]
    for key in ("ambulance_id", "responder_id", "hospital_id"):
        if action.get(key):
            parts.append(action[key])
    if action.get("victim_ids"):
        parts.append("[" + ", ".join(action["victim_ids"]) + "]")
    return " ".join(parts)


@feed_event("agent_message", "agent")
def _agent_message(e: dict) -> str:
    action = _action_text(e.get("proposed_action"))
    head = f"{e['sender']} → {e['recipient']}: {e['message_type']}"
    if e.get("incident_id"):
        head += f" ({e['incident_id']})"
    if e.get("round"):
        head += f" round {e['round']}"
    return head + (f" · {action}" if action else "") + (f" — {e['reason']}" if e.get("reason") else "")


@feed_event("conflict_detected", "conflict")
def _conflict_detected(e: dict) -> str:
    return f"Conflict {e['conflict_id']}: {e['reason']}"


@feed_event("conflict_resolved", "conflict")
def _conflict_resolved(e: dict) -> str:
    return f"Conflict {e['conflict_id']} resolved by {e['method']}"


@feed_event("action_accepted", "action")
def _action_accepted(e: dict) -> str:
    return f"Executed ({e['source']}): {_action_text(e['action'])} for {e['incident_id']}"


@feed_event("proposal_invalid", "action")
def _proposal_invalid(e: dict) -> str:
    return f"Invalid proposal from {e['agent']} ({e['tool']}): {e['reason']}. {e.get('detail', '')}"


@feed_event("incident_arrived", "incident")
def _incident_arrived(e: dict) -> str:
    return f"{e['incident_id']} reported: {e['victims']} victim(s), max severity {e['max_severity']}"


@feed_event("ambulance_on_scene", "movement")
def _on_scene(e: dict) -> str:
    return f"{e['ambulance_id']} on scene at {e['incident_id']}"


@feed_event("ambulance_departed", "movement")
def _departed(e: dict) -> str:
    return f"{e['ambulance_id']} leaves for {e['hospital_id']}"


@feed_event("ambulance_at_hospital", "hospital")
def _at_hospital(e: dict) -> str:
    return f"{e['ambulance_id']} arrived at {e['hospital_id']}"


@feed_event("handover_complete", "hospital")
def _handover(e: dict) -> str:
    return f"{e['hospital_id']} received {', '.join(e['victim_ids'])}"


@feed_event("treatment_started", "hospital")
def _treatment_started(e: dict) -> str:
    return f"{e['hospital_id']} started treating {e['victim_id']}"


@feed_event("victim_deteriorated", "incident")
def _deteriorated(e: dict) -> str:
    return f"{e['victim_id']} deteriorated to severity {e['severity']}"
