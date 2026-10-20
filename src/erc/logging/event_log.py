"""Append-only event log: the single record that metrics and the dashboard replay are built from."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class EventLog:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.events: list[dict[str, Any]] = []

    def record(self, t: int, kind: str, **data: Any) -> None:
        self.events.append({"t": t, "kind": kind, **data})

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["kind"] == kind]

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.run_id}.jsonl"
        with path.open("w") as f:
            for e in self.events:
                f.write(json.dumps(e) + "\n")
        return path

    @classmethod
    def load(cls, path: Path) -> EventLog:
        log = cls(path.stem)
        log.events = [json.loads(line) for line in path.read_text().splitlines() if line]
        return log