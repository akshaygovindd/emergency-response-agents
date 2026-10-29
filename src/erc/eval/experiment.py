"""Experiment runner: every system on every scenario and seed, with logs, metrics, and summaries."""
from __future__ import annotations

import json
from collections.abc import Callable

import pandas as pd

from erc.agents.negotiation import NegotiatingSystem
from erc.agents.system import AgentSystem
from erc.config import SCENARIO_DIR, Mode, ScenarioName, log_dir, require_writable, results_dir, seeds_for
from erc.eval.metrics import RunMetrics, compute_metrics
from erc.eval.stats import paired_comparison, summarize
from erc.models.state import Scenario
from erc.policies.greedy import GreedyPolicy
from erc.policies.naive import NaivePolicy
from erc.scenarios.generator import generate_scenario
from erc.sim.engine import Engine, Policy

POLICIES: dict[Mode, Callable[[], Policy]] = {
    Mode.NAIVE: NaivePolicy,
    Mode.GREEDY: GreedyPolicy,
    Mode.AGENTS: lambda: AgentSystem(negotiate=False),
    Mode.NEGOTIATION: lambda: NegotiatingSystem(),
    Mode.ORACLE: lambda: NegotiatingSystem(oracle=True),
}
AGENT_MODES = [Mode.AGENTS, Mode.NEGOTIATION, Mode.ORACLE]
KEY_METRICS = ["critical_service_rate", "critical_response_mean", "response_p95",
               "contacted_rate", "hospitalized_rate", "ambulance_utilization", "actions_rejected"]
COORDINATION_METRICS = ["conflicts", "resolved_by_negotiation", "resolved_by_fallback", "counters_accepted",
                        "invalid_proposals", "llm_calls", "tokens_in", "tokens_out", "est_cost_usd"]


def _clean(x):
    return None if x is None or pd.isna(x) else float(x)


def runs_file(version: str):
    return results_dir(version) / "runs.jsonl"


def _single_version(runs: list[dict]) -> str:
    """Tables never mix versions: all rows must carry the same version."""
    versions = {r.get("version") for r in runs}
    if len(versions) != 1 or None in versions:
        raise ValueError(f"Rows must all carry exactly one version, found {sorted(map(str, versions))}")
    return versions.pop()


def load_scenario(name: ScenarioName, seed: int) -> Scenario:
    path = SCENARIO_DIR / f"{name.value}_seed{seed}.json"
    return Scenario.load(path) if path.exists() else generate_scenario(name, seed)


def make_policy(mode: Mode, version: str) -> Policy:
    """v2 runs use the admission negotiation protocol; v1 and the baselines are unchanged."""
    policy = POLICIES[mode]()
    if version == "v2" and mode in AGENT_MODES:
        policy.admission_protocol = "v2"
    return policy


def run_one(name: ScenarioName, seed: int, mode: Mode, version: str,
            allow_v1_write: bool = False) -> RunMetrics:
    require_writable(version, allow_v1_write)
    if mode not in POLICIES:
        raise ValueError(f"Mode '{mode.value}' is not implemented yet")
    engine = Engine(load_scenario(name, seed), make_policy(mode, version))
    engine.run()
    engine.log.save(log_dir(version) / mode.value)
    return compute_metrics(engine.state, engine.log, mode.value)


def load_runs(version: str) -> list[dict]:
    path = runs_file(version)
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    if any(r.get("version") != version for r in rows):
        raise ValueError(f"{path} has rows that do not declare version {version}")
    return rows


def save_runs(runs: list[RunMetrics], version: str, allow_v1_write: bool = False) -> None:
    """Upsert by (scenario, seed, mode): rerunning a system replaces its old results."""
    require_writable(version, allow_v1_write)
    store = {(r["scenario"], r["seed"], r["mode"]): r for r in load_runs(version)}
    for m in runs:
        store[(m.scenario, m.seed, m.mode)] = {**m.model_dump(mode="json"), "version": version}
    path = runs_file(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in store.values()))


def run_experiment(modes: list[Mode], scenarios: list[ScenarioName], seeds: list[int] | None = None,
                   *, version: str, allow_v1_write: bool = False, progress: bool = True) -> list[RunMetrics]:
    require_writable(version, allow_v1_write)     # fail before any (possibly paid) run starts
    runs = []
    for name in scenarios:
        for seed in (seeds or seeds_for(name)):
            for mode in modes:
                m = run_one(name, seed, mode, version, allow_v1_write)
                save_runs([m], version, allow_v1_write)            # saved immediately, so a later crash never loses finished runs
                runs.append(m)
                if progress:
                    csr = "n/a" if m.critical_service_rate is None else f"{m.critical_service_rate:.0%}"
                    extra = f" | fresh tokens {m.fresh_tokens:,}" if m.llm_calls else ""
                    print(f"  {name.value:10} seed {seed}  {mode.value:12} critical service {csr}{extra}")
    return runs


def summary_table(runs: list[dict]) -> pd.DataFrame:
    version, df, rows = _single_version(runs), pd.DataFrame(runs), []
    for name in ScenarioName:
        for mode in Mode:
            g = df[(df["scenario"] == name.value) & (df["mode"] == mode.value)]
            if g.empty:
                continue
            row = {"version": version, "scenario": name.value, "mode": mode.value, "seeds": len(g)}
            for k in KEY_METRICS:
                s = summarize([_clean(x) for x in g[k]])
                row[k] = s.mean
                if k == "critical_service_rate":
                    row["csr_95ci"] = "n/a" if s.ci_low is None else f"[{s.ci_low:.2f}, {s.ci_high:.2f}]"
            rows.append(row)
    return pd.DataFrame(rows)


def coordination_table(runs: list[dict]) -> pd.DataFrame:
    """Conflicts, negotiation outcomes, reliability, and cost for the agent systems (means per run)."""
    version, df, rows = _single_version(runs), pd.DataFrame(runs), []
    for name in ScenarioName:
        for mode in AGENT_MODES:
            g = df[(df["scenario"] == name.value) & (df["mode"] == mode.value)]
            if g.empty:
                continue
            row = {"version": version, "scenario": name.value, "mode": mode.value, "seeds": len(g)}
            for k in COORDINATION_METRICS:
                row[k] = summarize([_clean(x) for x in g[k]]).mean if k in g.columns else None
            rows.append(row)
    return pd.DataFrame(rows)


def paired_table(runs: list[dict], baseline: str = "greedy",
                 metric: str = "critical_service_rate") -> pd.DataFrame:
    version, df, rows = _single_version(runs), pd.DataFrame(runs), []
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
                "version": version, "scenario": name.value, "mode": mode.value, "vs": baseline, "seeds": c.n,
                "mean_diff": c.mean_diff,
                "diff_95ci": "n/a" if c.ci_low is None else f"[{c.ci_low:+.2f}, {c.ci_high:+.2f}]",
                "wins/losses/ties": f"{c.wins}/{c.losses}/{c.ties}",
                "significant": c.significant,
            })
    return pd.DataFrame(rows)