"""Replay a saved run from its event log (no simulation, no API calls).

Positions in the log only change when a unit arrives, so for the minutes in between we
interpolate in a straight line from where the unit started to where it later arrived.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOGS_DIR = ROOT / "logs"
SCENARIOS_DIR = ROOT / "data" / "scenarios"
MODE_ORDER = ["naive", "greedy", "agents", "negotiation", "oracle"]
MOVING = ("en_route", "transporting")
_LOG_NAME = re.compile(r"^(?P<scenario>[a-z]+)_seed(?P<seed>\d+)_(?P<mode>[a-z]+)\.jsonl$")


@dataclass(frozen=True)
class RunRef:
    scenario: str
    seed: int
    mode: str
    path: Path

    @property
    def run_number(self) -> int:
        return self.seed - 41  # run 1 = seed 42


@dataclass
class Frame:
    """The world at one minute."""
    minute: int
    incidents: list[dict]
    ambulances: list[dict]
    responders: list[dict]
    hospitals: list[dict]
    kpis: dict = field(default_factory=dict)


def available_runs(logs_dir: Path = LOGS_DIR) -> list[RunRef]:
    runs = []
    for path in sorted(logs_dir.glob("*/*.jsonl")):
        m = _LOG_NAME.match(path.name)
        if m and m["mode"] == path.parent.name:
            runs.append(RunRef(m["scenario"], int(m["seed"]), m["mode"], path))
    return runs


def interpolate_track(states: list[tuple]) -> list[tuple[float, float]]:
    """Per-minute (x, y) for one unit from per-minute (x, y, status, target) samples.

    A move starts when the status becomes en_route/transporting and ends at the next minute
    the logged position jumps (the arrival). Minutes in between are linearly interpolated.
    """
    n = len(states)
    out = [(s[0], s[1]) for s in states]
    seg_start: int | None = None
    for m in range(n):
        x, y, status, _ = states[m]
        prev = states[m - 1] if m else None
        if prev is not None and seg_start is not None and (x, y) != (prev[0], prev[1]):
            x0, y0 = states[seg_start][:2]  # arrival: fill the minutes of the move
            span = m - seg_start
            for k in range(seg_start, m):
                f = (k - seg_start) / span
                out[k] = (round(x0 + (x - x0) * f, 2), round(y0 + (y - y0) * f, 2))
            seg_start = None
        if prev is None or status != prev[2]:
            seg_start = m if status in MOVING else None
    return out


class Replay:
    def __init__(self, events: list[dict], hospital_locations: dict[str, tuple[float, float]]):
        self.events = events
        self.snapshots = {e["time_min"]: e for e in events if e["kind"] == "snapshot"}
        self.last_minute = max(self.snapshots)
        self.hospital_locations = hospital_locations
        self._positions = {
            "ambulances": self._tracks("ambulances"),
            "responders": self._tracks("responders"),
        }

    @classmethod
    def load(cls, run: RunRef) -> Replay:
        events = [json.loads(line) for line in run.path.read_text().splitlines() if line]
        scenario = json.loads((SCENARIOS_DIR / f"{run.scenario}_seed{run.seed}.json").read_text())
        hospitals = {h["hospital_id"]: (h["location"]["x"], h["location"]["y"]) for h in scenario["hospitals"]}
        return cls(events, hospitals)

    def _tracks(self, group: str) -> dict[str, list[tuple[float, float]]]:
        minutes = sorted(self.snapshots)
        samples: dict[str, list[tuple]] = {}
        for m in minutes:
            for u in self.snapshots[m][group]:
                samples.setdefault(u["id"], []).append((u["x"], u["y"], u["status"], u["target"]))
        return {uid: interpolate_track(s) for uid, s in samples.items()}

    def frame(self, minute: int) -> Frame:
        minute = max(0, min(minute, self.last_minute))
        snap = self.snapshots[minute]
        units = {}
        for group in ("ambulances", "responders"):
            units[group] = [{**u, "x": self._positions[group][u["id"]][minute][0],
                             "y": self._positions[group][u["id"]][minute][1]} for u in snap[group]]
        hospitals = []
        for h in snap["hospitals"]:
            x, y = self.hospital_locations[h["id"]]
            hospitals.append({**h, "x": x, "y": y, "er_fraction": h["er_occupied"] / h["er_capacity"]})
        kpis = {k: snap[k] for k in ("active_incidents", "waiting_victims", "critical_waiting",
                                     "ambulances_busy", "ambulances_available")}
        return Frame(minute, snap["incidents"], units["ambulances"], units["responders"], hospitals, kpis)

    def events_until(self, minute: int) -> list[dict]:
        """Raw events up to and including this minute, in log order."""
        return [e for e in self.events if e["t"] <= minute and e["kind"] != "snapshot"]
