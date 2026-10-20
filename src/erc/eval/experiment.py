"""Experiment runner: every system on every scenario and seed, with logs, metrics, and summaries."""
from __future__ import annotations

import json
from collections.abc import Callable

import pandas as pd

from erc.config import LOG_DIR, RESULTS_DIR, SCENARIO_DIR, Mode, ScenarioName, seeds_for
from erc.eval.metrics import RunMetrics, compute_metrics
from erc.eval.stats import paired_comparison, summarize
from erc.models.state import Scenario
from erc.policies.greedy import GreedyPolicy
from erc.policies.naive import NaivePolicy
from erc.scenarios.generator import generate_scenario
from erc.sim.engine import Engine, Policy

# Agent modes get registered here once they exist
POLICIES: dict[Mode, Callable[[], Policy]] = {
    Mode.NAIVE: NaivePolicy,
    Mode.GREEDY: GreedyPolicy,
}
RUNS_FILE = RESULTS_DIR / "runs.jsonl"
KEY_METRICS = ["critical_service_rate", "critical_response_mean", "response_p95",
               "contacted_rate", "hospitalized_rate", "ambulance_utilization", "actions_rejected"]


def _clean(x):
    return None if x is None or pd.isna(x) else float(x)


def load_scenario(name: ScenarioName, seed: int) -> Scenario:
    path = SCENARIO_DIR / f"{name.value}_seed{seed}.json"
    return Scenario.load(path) if path.exists() else generate_scenario(name, seed)


def run_one(name: ScenarioName, seed: int, mode: Mode) -> RunMetrics:
    if mode not in POLICIES:
        raise ValueError(f"Mode '{mode.value}' is not implemented yet")
    engine = Engine(load_scenario(name, seed), POLICIES[mode]())
    engine.run()
    engine.log.save(LOG_DIR / mode.value)
    return compute_metrics(engine.state, engine.log, mode.value)


def load_runs() -> list[dict]:
    if not RUNS_FILE.exists():
        return []
    return [json.loads(line) for line in RUNS_FILE.read_text().splitlines() if line]


def save_runs(runs: list[RunMetrics]) -> None:
    """Upsert by (scenario, seed, mode): rerunning a system replaces its old results."""
    store = {(r["scenario"], r["seed"], r["mode"]): r for r in load_runs()}
    for m in runs:
        store[(m.scenario, m.seed, m.mode)] = m.model_dump(mode="json")
    RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUNS_FILE.write_text("".join(json.dumps(r) + "\n" for r in store.values()))


def run_experiment(modes: list[Mode], scenarios: list[ScenarioName], seeds: list[int] | None = None,
                   progress: bool = True) -> list[RunMetrics]:
    runs = []
    for name in scenarios:
        for seed in (seeds or seeds_for(name)):
            for mode in modes:
                m = run_one(name, seed, mode)
                runs.append(m)
                if progress:
                    csr = "n/a" if m.critical_service_rate is None else f"{m.critical_service_rate:.0%}"
                    print(f"  {name.value:10} seed {seed}  {mode.value:12} critical service {csr}")
    save_runs(runs)
    return runs


def summary_table(runs: list[dict]) -> pd.DataFrame:
    df, rows = pd.DataFrame(runs), []
    for name in ScenarioName:
        for mode in Mode:
            g = df[(df["scenario"] == name.value) & (df["mode"] == mode.value)]
            if g.empty:
                continue
            row = {"scenario": name.value, "mode": mode.value, "seeds": len(g)}
            for k in KEY_METRICS:
                s = summarize([_clean(x) for x in g[k]])
                row[k] = s.mean
                if k == "critical_service_rate":
                    row["csr_95ci"] = "n/a" if s.ci_low is None else f"[{s.ci_low:.2f}, {s.ci_high:.2f}]"
            rows.append(row)
    return pd.DataFrame(rows)


def paired_table(runs: list[dict], baseline: str = "greedy",
                 metric: str = "critical_service_rate") -> pd.DataFrame:
    df, rows = pd.DataFrame(runs), []
    for name in ScenarioName:
        sub = df[df["scenario"] == name.value]
        base = sub[sub["mode"] == baseline].set_index("seed")[metric]
        for mode in Mode:
            if mode.value == baseline:
                continue
            other = sub[sub["mode"] == mode.value].set_index("seed")[metric]
            seeds = sorted(set(base.index) & set(other.index))
            if not seeds:
                continue
            c = paired_comparison([_clean(other[s]) for s in seeds], [_clean(base[s]) for s in seeds])
            rows.append({
                "scenario": name.value, "mode": mode.value, "vs": baseline, "seeds": c.n,
                "mean_diff": c.mean_diff,
                "diff_95ci": "n/a" if c.ci_low is None else f"[{c.ci_low:+.2f}, {c.ci_high:+.2f}]",
                "wins/losses/ties": f"{c.wins}/{c.losses}/{c.ties}",
                "significant": c.significant,
            })
    return pd.DataFrame(rows)