"""What-if: generate a modified scenario in memory and run the two baseline systems on it, live.

Nothing is saved: no scenario file, no log, no results row. The frozen generator settings in config.py are
only read (a modified copy of one scenario's settings is used); the same builders that make the saved
scenarios make this one, so a what-if with the original numbers equals the saved scenario exactly.
Only naive and greedy run here: they use no LLM and take about a second. Agent systems are not run.
"""
from __future__ import annotations

import json

import numpy as np

from erc.config import SCENARIOS, SETTINGS, ScenarioName
from erc.dashboard.export import build_bundle
from erc.eval.metrics import compute_metrics
from erc.models.state import Scenario
from erc.policies.greedy import GreedyPolicy
from erc.policies.naive import NaivePolicy
from erc.scenarios import generator as gen
from erc.sim.engine import Engine

LIVE_SYSTEMS = {"naive": NaivePolicy, "greedy": GreedyPolicy}
AMBULANCES = (2, 5)
INCIDENTS = (3, 40)


def build_scenario(ambulances: int, incidents: int, seed: int, profile: ScenarioName = ScenarioName.NORMAL) -> Scenario:
    """A scenario with `ambulances` ambulances and `incidents` incidents; severity mix and arrival window
    come from the chosen base profile. The module-level SCENARIOS table is never modified."""
    if not AMBULANCES[0] <= ambulances <= AMBULANCES[1]:
        raise ValueError(f"ambulances must be {AMBULANCES[0]}-{AMBULANCES[1]}")
    if not INCIDENTS[0] <= incidents <= INCIDENTS[1]:
        raise ValueError(f"incidents must be {INCIDENTS[0]}-{INCIDENTS[1]}")
    cfg = SCENARIOS[profile].model_copy(update={"n_incidents": incidents,
                                                "ambulances_out_of_service": SETTINGS.env.n_ambulances - ambulances})
    rng = np.random.default_rng([seed, gen.SCENARIO_INDEX[profile]])
    return Scenario(name=profile, seed=seed, hospitals=gen._build_hospitals(cfg.trauma_prefill),
                    ambulances=gen._build_ambulances(cfg.ambulances_out_of_service),
                    responders=gen._build_responders(), staff=gen._build_staff(),
                    incidents=gen._draw_incidents(rng, cfg))


def run_system(scenario: Scenario, mode: str) -> dict:
    """Run one live system on the scenario: {bundle, metrics}. Events stay in memory."""
    engine = Engine(scenario, LIVE_SYSTEMS[mode]())
    engine.run()
    metrics = compute_metrics(engine.state, engine.log, mode)
    meta = {"version": "what-if", "scenario": scenario.name.value, "seed": scenario.seed, "mode": mode,
            "run_number": scenario.seed - 41}
    bundle = build_bundle(engine.log.events, json.loads(scenario.model_dump_json()), meta)
    return {"bundle": bundle, "metrics": metrics.model_dump(mode="json")}


def run_whatif(ambulances: int, incidents: int, seed: int, profile: ScenarioName = ScenarioName.NORMAL) -> dict:
    """{mode: {bundle, metrics}} for naive and greedy on the same modified scenario."""
    scenario = build_scenario(ambulances, incidents, seed, profile)
    return {mode: run_system(scenario, mode) for mode in LIVE_SYSTEMS}


# ───────── Page helpers ─────────
DEFAULTS = {"amb": 5, "inc": 12, "seed": 42, "profile": "normal"}
PROFILES = {"normal": "Normal", "surge": "Surge mix", "bottleneck": "Bottleneck"}


def parse_params(amb, inc, seed, profile) -> tuple[int, int, int, ScenarioName]:
    """Page-address values to a safe (ambulances, incidents, seed, profile); anything unusable falls back to the default."""
    def number(value, default, lo, hi):
        try:
            return min(hi, max(lo, int(value)))
        except (TypeError, ValueError):
            return default
    name = profile if profile in PROFILES else DEFAULTS["profile"]
    return (number(amb, DEFAULTS["amb"], *AMBULANCES), number(inc, DEFAULTS["inc"], *INCIDENTS),
            number(seed, DEFAULTS["seed"], 0, 9999), ScenarioName(name))


def summarize_run(metrics: dict) -> dict:
    """The few numbers the result cards show, from a run's metrics."""
    n_crit = metrics["n_critical"]
    served = n_crit - metrics["critical_unserved"] if n_crit else 0
    return {"csr": metrics["critical_service_rate"], "n_critical": n_crit, "n_victims": metrics["n_victims"],
            "reached": metrics["contacted_rate"], "response": metrics["response_mean"], "never_reached": metrics["critical_unserved"],
            "served_note": f"{served} of {n_crit} critical patients in time · {metrics['n_victims']} patients total" if n_crit else f"no critical patients · {metrics['n_victims']} patients total"}


def difference_points(summaries: dict) -> float | None:
    """Greedy minus naive in percentage points (None if either has no critical patients)."""
    a, b = summaries["greedy"]["csr"], summaries["naive"]["csr"]
    return None if a is None or b is None else round((a - b) * 100, 1)
