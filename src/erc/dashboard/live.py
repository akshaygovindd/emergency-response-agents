"""Live numbers for the replay player: KPIs, hospital status, and resource use, per minute.

Everything is derived from the run log and the scenario (no simulation). The player only displays it.
"""
from __future__ import annotations

NEAR_CAPACITY, MODERATE = 0.85, 0.5          # share of ER beds occupied or promised
STATUS_STABLE, STATUS_MODERATE, STATUS_NEAR = "Stable", "Moderate", "Near capacity"
AMBULANCE_STATES = ("available", "en_route", "on_scene", "transporting")


def hospital_status(occupied: int, promised: int, capacity: int) -> str:
    load = (occupied + promised) / capacity if capacity else 1.0
    return STATUS_NEAR if load >= NEAR_CAPACITY else STATUS_MODERATE if load >= MODERATE else STATUS_STABLE


def kpis_by_minute(victims: list[dict], conflicts: list[dict], last_minute: int) -> list[dict]:
    """Per minute: critical victims reached in time, victims reached, Expectant, conflicts, response time.

    A critical victim is "in time" if first contact came within the deadline, and "Expectant" once the
    deadline has passed without that (the same rule as the map's black dots, counted cumulatively).
    """
    out = []
    for t in range(last_minute + 1):
        arrived = [v for v in victims if v["arrival_min"] <= t]
        critical = [v for v in arrived if v["severity"] >= 4]
        reached = [v for v in arrived if v["contact_min"] is not None and v["contact_min"] <= t]
        in_time = [v for v in critical if _in_time(v, t)]
        expectant = [v for v in critical if t - v["arrival_min"] > v["deadline_min"] and not _in_time(v, t)]
        seen = [c for c in conflicts if c["t"] <= t]
        waits = [v["contact_min"] - v["arrival_min"] for v in reached]
        out.append({"crit_ok": len(in_time), "crit_n": len(critical), "reached": len(reached),
                    "arrived": len(arrived), "expectant": len(expectant), "conflicts": len(seen),
                    "negotiated": sum(c["method"] == "negotiation" for c in seen),
                    "resp_avg": round(sum(waits) / len(waits), 1) if waits else None})
    return out


def _in_time(v: dict, t: int) -> bool:
    return (v["contact_min"] is not None and v["contact_min"] <= t
            and v["contact_min"] - v["arrival_min"] <= v["deadline_min"])


def staff_in_use_by_minute(events: list[dict], scenario: dict, last_minute: int) -> list[list[list[int]]]:
    """Per minute, per hospital: [doctors with a patient, nurses with a patient] (from treatment events)."""
    hospital_ids = [h["hospital_id"] for h in scenario["hospitals"]]
    by_minute: dict[int, list[dict]] = {}
    for e in events:
        if e["kind"] in ("treatment_started", "treatment_finished"):
            by_minute.setdefault(e["t"], []).append(e)
    active: dict[str, tuple[str, str, str]] = {}           # victim -> (hospital, doctor, nurse)
    out = []
    for t in range(last_minute + 1):
        for e in by_minute.get(t, []):
            if e["kind"] == "treatment_started":
                active[e["victim_id"]] = (e["hospital_id"], e.get("doctor_id"), e.get("nurse_id"))
            else:
                active.pop(e["victim_id"], None)
        out.append([[len({d for h, d, _ in active.values() if h == hid and d}),
                     len({n for h, _, n in active.values() if h == hid and n})] for hid in hospital_ids])
    return out


def staff_totals(scenario: dict) -> dict[str, dict[str, int]]:
    """hospital_id -> {'doctors': n, 'nurses': n} on shift."""
    totals = {h["hospital_id"]: {"doctors": 0, "nurses": 0} for h in scenario["hospitals"]}
    for s in scenario.get("staff", []):
        if s.get("on_shift", True) and s["hospital_id"] in totals:
            totals[s["hospital_id"]]["doctors" if s["role"] == "doctor" else "nurses"] += 1
    return totals


def resources_for_frame(amb_rows: list[list], team_rows: list[list], team_kinds: list[str]) -> dict:
    """Ambulances by status, and responder teams busy or free, for one minute."""
    amb = {state: 0 for state in AMBULANCE_STATES}
    for row in amb_rows:
        amb[row[2]] = amb.get(row[2], 0) + 1
    teams = [[kind, row[2] != "available"] for kind, row in zip(team_kinds, team_rows)]
    return {"amb": amb, "teams": teams,
            "teams_busy": sum(busy for _, busy in teams), "teams_free": sum(not busy for _, busy in teams)}


def utilization_by_minute(events: list[dict], scenario: dict, staff: list[list[list[int]]], last_minute: int) -> list[dict]:
    """Per minute, for the five resources the brief names: {now, avg, busy, total} (now and avg are fractions 0-1).

    ambulances / teams: busy share from the run's snapshots (the same numbers the results table averages, so
    the last minute's `avg` equals the results' utilization); doctors / nurses: share with a patient in
    treatment; ER: occupied waiting beds over total ER capacity. `avg` is the mean of `now` from minute 0 up to
    that minute.
    """
    snaps = {e["time_min"]: e for e in events if e["kind"] == "snapshot"}
    n_amb, n_team = len(scenario["ambulances"]), len(scenario["responders"])
    caps = {h["hospital_id"]: h["er_capacity"] for h in scenario["hospitals"]}
    totals = staff_totals(scenario)
    n_doc, n_nurse = (sum(v[k] for v in totals.values()) for k in ("doctors", "nurses"))
    sums = {k: 0.0 for k in ("amb", "teams", "doctors", "nurses", "er")}
    out = []
    for t in range(last_minute + 1):
        s = snaps[t]
        rows = {"amb": (s["ambulances_busy"], n_amb), "teams": (n_team - s["responders_available"], n_team),
                "doctors": (sum(h[0] for h in staff[t]), n_doc), "nurses": (sum(h[1] for h in staff[t]), n_nurse),
                "er": (sum(round(s["er_occupancy"][h] * c) for h, c in caps.items()), sum(caps.values()))}
        frame = {}
        for key, (busy, total) in rows.items():
            now = busy / total if total else 0.0
            sums[key] += now
            frame[key] = {"busy": busy, "total": total, "now": round(now, 4), "avg": round(sums[key] / (t + 1), 4)}
        out.append(frame)
    return out
