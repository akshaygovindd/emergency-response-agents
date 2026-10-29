"""Agent activity timeline for the replay app: plain-language items built from the feed rows (story.py).

One item per message, except that a run of consecutive "executed" lines becomes one item ("Sent 4 units").
Commit lines are internal bookkeeping and are left out. Internal IDs stay in `tip` (shown on hover).

Item: {id, a, b, t, who, icon, type, tag, text, tip}
  a, b   first and last feed-row index covered, so the player shows an item once b < frame["n"]
"""
from __future__ import annotations

from erc.dashboard.story import plain_text

WHO = {"Assessment": "Assessment", "Dispatch": "Dispatch", "Resource Alloc.": "Resource Allocation",
       "Hospital": "Hospital", "System": "System"}
ICON = {"Assessment": "brain-circuit", "Dispatch": "siren", "Resource Allocation": "sliders-horizontal",
        "Hospital": "hospital", "System": "shield-check"}
TAGS = {"proposal": "Proposal", "counter": "Counter", "accept": "Accept", "reject": "Declined", "conflict": "Conflict",
        "executed": "Executed", "escalate": "Escalated", "info": "Assessed"}
SKIPPED = {"commit"}


def _sentence(row: dict) -> str:
    kind, body = row["type"], plain_text(row["text"])
    short = body.removeprefix("send ")
    if kind == "proposal":
        return f"Proposed to {body}"
    if kind == "counter":
        return f"Suggested instead: {short}"
    if kind == "accept":
        return f"Accepted: {short}"
    if kind == "reject":
        return f"Declined: {short}"
    if kind == "conflict":
        return f"Conflict: {body}"
    if kind == "escalate":
        return f"Escalated to arbitration: {short}"
    if kind == "info":
        return "Assessed " + body.removeprefix("assess ")
    return body


def _item(row: dict, who: str) -> dict:
    return {"id": row["id"], "a": row["i"], "b": row["i"], "t": row["t"], "who": who, "icon": ICON.get(who, "shield-check"),
            "type": row["type"], "tag": TAGS.get(row["type"], row["type"].title()), "text": _sentence(row),
            "tip": f"{row['id']} - {row['why']}" if row["why"] else row["id"]}


def timeline_items(rows: list[dict]) -> list[dict]:
    items: list[dict] = []
    group: list[dict] = []

    def flush() -> None:
        if not group:
            return
        units = [plain_text(r["text"].removeprefix("sent ").split(" to ")[0]) for r in group]
        items.append({"id": group[0]["id"], "a": group[0]["i"], "b": group[-1]["i"], "t": group[0]["t"], "who": "System",
                      "icon": ICON["System"], "type": "executed", "tag": TAGS["executed"],
                      "text": (f"Sent {len(group)} units: " + ", ".join(units)) if len(group) > 1 else f"Sent {units[0]}",
                      "tip": "; ".join(f"{r['id']} - {plain_text(r['text'])}" for r in group)})
        group.clear()

    for row in rows:
        if row["type"] in SKIPPED:
            continue
        if row["type"] == "executed":
            group.append(row)
            continue
        flush()
        items.append(_item(row, WHO.get(row["from"], row["from"])))
    flush()
    return items
