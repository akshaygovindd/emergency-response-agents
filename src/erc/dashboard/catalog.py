"""Which saved runs exist, as a small nested table for the run selector: {version: {scenario: {run: [modes]}}}."""
from __future__ import annotations

from erc.dashboard.replay import MODE_ORDER, RunRef

SCENARIO_ORDER = ["normal", "surge", "bottleneck"]


def run_catalog(runs: list[RunRef]) -> dict:
    out: dict = {}
    for r in runs:
        out.setdefault(r.version, {}).setdefault(r.scenario, {}).setdefault(str(r.run_number), []).append(r.mode)
    return {v: {s: {n: sorted(set(modes), key=MODE_ORDER.index) for n, modes in sorted(by_run.items(), key=lambda kv: int(kv[0]))}
                for s, by_run in sorted(by_scenario.items(), key=lambda kv: SCENARIO_ORDER.index(kv[0]) if kv[0] in SCENARIO_ORDER else 99)}
            for v, by_scenario in sorted(out.items())}


def resolve_selection(catalog: dict, version: str | None, scenario: str | None, run: str | None, mode: str | None,
                      default: tuple = ("v1", "normal", "1", "negotiation")) -> tuple[str, str, str, str]:
    """The requested run if it exists, otherwise the closest one that does (keeps as much of the request as possible)."""
    v = version if version in catalog else default[0] if default[0] in catalog else next(iter(catalog))
    s = scenario if scenario in catalog[v] else default[1] if default[1] in catalog[v] else next(iter(catalog[v]))
    r = run if run in catalog[v][s] else default[2] if default[2] in catalog[v][s] else next(iter(catalog[v][s]))
    m = mode if mode in catalog[v][s][r] else default[3] if default[3] in catalog[v][s][r] else catalog[v][s][r][0]
    return v, s, r, m
