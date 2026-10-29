"""Export a saved run as one JSON-serialisable bundle for the browser replay player.

Python owns all logic (positions, trips, triage colours, first contact, promised beds); the player
only draws frames. Built from a run's event log and its scenario file: no simulation, no API calls.

Bundle layout (all minutes are integers, positions are km on the 20 x 20 grid):
  meta       run label, last_minute, grid_km
  hospitals  [{id, name, label, x, y, er_capacity, treatment_slots}]
  ambulances [{id, als}]          responders [{id, kind}]
  incidents  [{id, x, y, arrival_min}]
  victims    [{id, incident, severity, deadline_min, arrival_min, contact_min | null}]
  frames[t]  {v: [triage code per victim], h: [[er, treatment_in_use, promised, status] per hospital],
              a: [[x, y, status, target, onboard] per ambulance], r: [[x, y, status, target] per responder],
              k: KPIs, res: ambulances/teams in use, s: [[doctors, nurses] in use per hospital], n: messages so far}
  messages   feed rows (see story.py)        conflicts  negotiation chains (see story.py)
  tour       [{t, title, caption}] bookmarked moments (see tour.py)
  trips      [{unit, kind, t0, t1, x0, y0, x1, y1, target}]   straight-line moves, for sub-minute gliding
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from erc.dashboard.live import (
    hospital_status, kpis_by_minute, resources_for_frame, staff_in_use_by_minute, staff_totals,
)
from erc.dashboard.replay import LOGS_DIR, SCENARIOS_DIR, MOVING, Replay, interpolate_track
from erc.dashboard.story import conflict_chains, feed_messages
from erc.dashboard.tour import tour_moments

GRID_KM = 20
# Triage codes for victims in frames[t]["v"]
HIDDEN, IMMEDIATE, DELAYED, MINOR, EXPECTANT, REACHED = range(6)
CODE_NAMES = {HIDDEN: "hidden", IMMEDIATE: "immediate", DELAYED: "delayed", MINOR: "minor",
              EXPECTANT: "expectant", REACHED: "reached"}
MOVE_EPS_KM = 0.005          # positions are rounded to 0.01 km, so smaller steps are noise
TURN_TOLERANCE_KM = 0.1      # a change in per-minute step larger than this starts a new trip
HOSPITAL_LABELS = {"trauma": "Trauma", "burn": "Burn", "general": "General"}


def _triage_code(severity: int) -> int:
    return IMMEDIATE if severity >= 4 else DELAYED if severity == 3 else MINOR


def _hospital_label(name: str) -> str:
    low = name.lower()
    return next((label for key, label in HOSPITAL_LABELS.items() if key in low), name)


# ───────── First contact (same rule as the engine, read from the log) ─────────
def first_contacts(events: list[dict], scenario: dict) -> dict[str, int]:
    """victim_id -> minute of first medical contact.

    An ambulance reaching the scene reaches the victims it was assigned; a medical team reaching an
    incident reaches every victim there who was still waiting.
    """
    medical = {r["team_id"] for r in scenario["responders"] if r["responder_type"] == "medical"}
    incidents = {i["incident_id"]: [v["victim_id"] for v in i["victims"]] for i in scenario["incidents"]}
    waiting_at = {e["time_min"]: {v["id"]: v["status"] for i in e["incidents"] for v in i["victims"]}
                  for e in events if e["kind"] == "snapshot"}
    assigned: dict[tuple[str, str], list[str]] = {}
    contact: dict[str, int] = {}
    for e in events:
        if e["kind"] == "action_accepted" and e["action"]["action_type"] == "assign_ambulance":
            assigned[(e["action"]["ambulance_id"], e["incident_id"])] = list(e["action"]["victim_ids"])
        elif e["kind"] == "ambulance_on_scene":
            for vid in assigned.get((e["ambulance_id"], e["incident_id"]), []):
                contact.setdefault(vid, e["t"])
        elif e["kind"] == "responder_arrived" and e["team_id"] in medical:
            status = waiting_at.get(e["t"], {})
            for vid in incidents.get(e["incident_id"], []):
                if status.get(vid) == "waiting":
                    contact.setdefault(vid, e["t"])
    return contact


# ───────── Promised beds ─────────
def promised_by_minute(events: list[dict], hospital_ids: list[str], last_minute: int) -> list[dict[str, int]]:
    """Per minute, victims admitted to each hospital who have not been handed over yet."""
    by_minute: dict[int, list[dict]] = {}
    for e in events:
        if e["kind"] in ("action_accepted", "handover_complete"):
            by_minute.setdefault(e["t"], []).append(e)
    destination: dict[str, str] = {}
    out = []
    for t in range(last_minute + 1):
        for e in by_minute.get(t, []):
            if e["kind"] == "handover_complete":
                for vid in e["victim_ids"]:
                    destination.pop(vid, None)
            elif e["action"]["action_type"] in ("admit_patient", "divert_patient"):
                for vid in e["action"]["victim_ids"]:
                    destination[vid] = e["action"]["hospital_id"]
        out.append({h: sum(1 for d in destination.values() if d == h) for h in hospital_ids})
    return out


# ───────── Trips ─────────
def unit_trips(unit_id: str, kind: str, positions: list[tuple[float, float]], targets: list) -> list[dict]:
    """Straight-line moves of one unit, from its per-minute positions."""
    trips, start, prev_step = [], None, None
    for m in range(1, len(positions)):
        dx, dy = positions[m][0] - positions[m - 1][0], positions[m][1] - positions[m - 1][1]
        moved = math.hypot(dx, dy) > MOVE_EPS_KM
        turned = (moved and prev_step is not None
                  and math.hypot(dx - prev_step[0], dy - prev_step[1]) > TURN_TOLERANCE_KM)
        if start is not None and (not moved or turned):
            trips.append(_trip(unit_id, kind, positions, targets, start, m - 1))
            start = None
        if moved and start is None:
            start = m - 1
        prev_step = (dx, dy) if moved else None
    if start is not None:
        trips.append(_trip(unit_id, kind, positions, targets, start, len(positions) - 1))
    return trips


def _trip(unit_id: str, kind: str, positions: list, targets: list, t0: int, t1: int) -> dict:
    target = next((t for t in targets[t0:t1 + 1] if t), None)
    return {"unit": unit_id, "kind": kind, "t0": t0, "t1": t1,
            "x0": positions[t0][0], "y0": positions[t0][1], "x1": positions[t1][0], "y1": positions[t1][1],
            "target": target}


# ───────── Bundle ─────────
def build_bundle(events: list[dict], scenario: dict, meta: dict) -> dict:
    hospital_xy = {h["hospital_id"]: (h["location"]["x"], h["location"]["y"]) for h in scenario["hospitals"]}
    replay = Replay(events, hospital_xy)
    last = replay.last_minute
    contact = first_contacts(events, scenario)

    victims = [{"id": v["victim_id"], "incident": i["incident_id"], "severity": int(v["severity"]),
                "deadline_min": v["deadline_min"], "arrival_min": i["arrival_time_min"],
                "contact_min": contact.get(v["victim_id"])}
               for i in scenario["incidents"] for v in i["victims"]]
    hospital_ids = [h["hospital_id"] for h in scenario["hospitals"]]
    promised = promised_by_minute(events, hospital_ids, last)
    messages, conflicts = feed_messages(events), conflict_chains(events)
    kpis = kpis_by_minute(victims, conflicts, last)
    staff = staff_in_use_by_minute(events, scenario, last)
    totals = staff_totals(scenario)
    seen = 0

    ambulances = [{"id": a["ambulance_id"], "als": a["ambulance_type"] == "advanced_life_support"}
                  for a in scenario["ambulances"]]
    responders = [{"id": r["team_id"], "kind": r["responder_type"]} for r in scenario["responders"]]

    frames, tracks = [], {u["id"]: ([], []) for u in ambulances + responders}
    for t in range(last + 1):
        f = replay.frame(t)
        current = {v["id"]: v["severity"] for i in f.incidents for v in i["victims"]}
        codes = []
        for v in victims:
            sev = current.get(v["id"])
            if sev is None or t < v["arrival_min"]:
                codes.append(HIDDEN)
            elif v["contact_min"] is not None and t >= v["contact_min"]:
                codes.append(REACHED)
            elif v["severity"] >= 4 and t - v["arrival_min"] > v["deadline_min"]:
                codes.append(EXPECTANT)
            else:
                codes.append(_triage_code(sev))
        amb = {a["id"]: a for a in f.ambulances}
        res = {r["id"]: r for r in f.responders}
        for unit in ambulances:
            a = amb[unit["id"]]
            tracks[unit["id"]][0].append((a["x"], a["y"]))
            tracks[unit["id"]][1].append(a["target"])
        for unit in responders:
            r = res[unit["id"]]
            tracks[unit["id"]][0].append((r["x"], r["y"]))
            tracks[unit["id"]][1].append(r["target"])
        hospitals = {h["id"]: h for h in f.hospitals}
        while seen < len(messages) and messages[seen]["t"] <= t:
            seen += 1
        amb_rows = [[amb[u["id"]]["x"], amb[u["id"]]["y"], amb[u["id"]]["status"], amb[u["id"]]["target"],
                     len(amb[u["id"]]["onboard"])] for u in ambulances]
        team_rows = [[res[u["id"]]["x"], res[u["id"]]["y"], res[u["id"]]["status"], res[u["id"]]["target"]]
                     for u in responders]
        frames.append({
            "t": t, "v": codes,
            "h": [[hospitals[h]["er_occupied"], hospitals[h]["treatment_in_use"], promised[t][h],
                   hospital_status(hospitals[h]["er_occupied"], promised[t][h], hospitals[h]["er_capacity"])]
                  for h in hospital_ids],
            "a": amb_rows, "r": team_rows, "k": kpis[t], "s": staff[t], "n": seen,
            "res": resources_for_frame(amb_rows, team_rows, [u["kind"] for u in responders]),
        })

    trips = []
    for kind, units in (("ambulance", ambulances), ("responder", responders)):
        for u in units:
            positions, targets = tracks[u["id"]]
            trips += unit_trips(u["id"], kind, positions, targets)
    trips.sort(key=lambda tr: (tr["t0"], tr["unit"]))

    return {
        "meta": {**meta, "last_minute": last, "grid_km": GRID_KM, "codes": CODE_NAMES,
                 "critical_total": sum(v["severity"] >= 4 for v in victims)},
        "hospitals": [{"id": h["hospital_id"], "name": h["name"], "label": _hospital_label(h["name"]),
                       "x": h["location"]["x"], "y": h["location"]["y"], "er_capacity": h["er_capacity"],
                       "treatment_slots": sum(h["treatment_slots"].values())
                       if isinstance(h["treatment_slots"], dict) else h["treatment_slots"],
                       **totals[h["hospital_id"]]}
                      for h in scenario["hospitals"]],
        "ambulances": ambulances, "responders": responders,
        "incidents": [{"id": i["incident_id"], "x": i["location"]["x"], "y": i["location"]["y"],
                       "arrival_min": i["arrival_time_min"]} for i in scenario["incidents"]],
        "victims": victims, "frames": frames, "trips": trips, "messages": messages, "conflicts": conflicts,
        "tour": tour_moments(events, conflicts, last, frames[-1]["k"], sum(v["severity"] >= 4 for v in victims)),
    }


def export_replay(version: str, scenario: str, seed: int, mode: str,
                  logs_dir: Path = LOGS_DIR, scenarios_dir: Path = SCENARIOS_DIR) -> dict:
    """Bundle for logs/<version>/<mode>/<scenario>_seed<seed>_<mode>.jsonl."""
    path = logs_dir / version / mode / f"{scenario}_seed{seed}_{mode}.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines() if line]
    data = json.loads((scenarios_dir / f"{scenario}_seed{seed}.json").read_text())
    meta = {"version": version, "scenario": scenario, "seed": seed, "mode": mode, "run_number": seed - 41}
    return build_bundle(events, data, meta)
