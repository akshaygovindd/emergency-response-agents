"""Numbers and one-sentence takeaways for the Results page, computed from results/<version>/runs.jsonl.

Read-only: the same statistics helpers as the experiment tables (95% t intervals, paired differences by
seed), but returned as numeric tables for charts. Each takeaway is generated from the numbers it sits under,
so every sentence traces to results/<version>/. One version at a time; versions are never mixed.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from erc.config import SCENARIO_DIR
from erc.eval.experiment import load_runs
from erc.eval.stats import paired_comparison, summarize

SCENARIOS = ["normal", "surge", "bottleneck"]
SYSTEMS = ["naive", "greedy", "agents", "negotiation", "oracle"]
AGENT_SYSTEMS = ["agents", "negotiation", "oracle"]
TRIAGE = {"Immediate": (4, 5), "Delayed": (3,), "Minor": (1, 2)}
FRAMES = {"v1": "v1 (frozen pilot)", "v2": "v2 (frozen, with hospital admission negotiation)"}


def runs_for(version: str) -> list[dict]:
    return load_runs(version)


def _present(runs: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(runs)


def csr_table(runs: list[dict]) -> pd.DataFrame:
    """Critical service rate per scenario and system: mean over seeds with its 95% CI."""
    df, rows = _present(runs), []
    for scenario in SCENARIOS:
        for mode in SYSTEMS:
            g = df[(df["scenario"] == scenario) & (df["mode"] == mode)]
            if g.empty:
                continue
            s = summarize([None if pd.isna(x) else float(x) for x in g["critical_service_rate"]])
            rows.append({"scenario": scenario, "mode": mode, "n": s.n, "mean": s.mean,
                         "ci_low": s.ci_low if s.ci_low is not None else s.mean,
                         "ci_high": s.ci_high if s.ci_high is not None else s.mean})
    return pd.DataFrame(rows, columns=["scenario", "mode", "n", "mean", "ci_low", "ci_high"])


def paired_table(runs: list[dict], mode: str, baseline: str) -> pd.DataFrame:
    """Seed-by-seed difference (mode - baseline) in critical service rate per scenario, with 95% CI."""
    df, rows = _present(runs), []
    for scenario in SCENARIOS:
        sub = df[df["scenario"] == scenario]
        base = sub[sub["mode"] == baseline].set_index("seed")["critical_service_rate"]
        other = sub[sub["mode"] == mode].set_index("seed")["critical_service_rate"]
        seeds = sorted(set(base.index) & set(other.index))
        if not seeds:
            continue
        c = paired_comparison([float(other[s]) for s in seeds], [float(base[s]) for s in seeds])
        rows.append({"scenario": scenario, "mode": mode, "vs": baseline, "n": c.n, "mean_diff": c.mean_diff,
                     "ci_low": c.ci_low if c.ci_low is not None else c.mean_diff,
                     "ci_high": c.ci_high if c.ci_high is not None else c.mean_diff,
                     "wins": c.wins, "losses": c.losses, "ties": c.ties, "significant": c.significant})
    return pd.DataFrame(rows, columns=["scenario", "mode", "vs", "n", "mean_diff", "ci_low", "ci_high",
                                       "wins", "losses", "ties", "significant"])


def triage_table(runs: list[dict], scenario_dir: Path = SCENARIO_DIR) -> pd.DataFrame:
    """Share of victims served in time per START colour, weighting each severity by how many victims it had."""
    counts: dict[tuple[str, int], dict[int, int]] = {}
    def severity_counts(scenario: str, seed: int) -> dict[int, int]:
        if (scenario, seed) not in counts:
            data = json.loads((scenario_dir / f"{scenario}_seed{seed}.json").read_text())
            c: dict[int, int] = defaultdict(int)
            for inc in data["incidents"]:
                for v in inc["victims"]:
                    c[int(v["severity"])] += 1
            counts[(scenario, seed)] = c
        return counts[(scenario, seed)]

    per_run: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for r in runs:
        n = severity_counts(r["scenario"], r["seed"])
        rates = {int(k): v for k, v in r["service_rate_by_severity"].items()}
        for color, levels in TRIAGE.items():
            total = sum(n.get(k, 0) for k in levels)
            if total:
                per_run[(r["scenario"], r["mode"], color)].append(
                    sum(rates.get(k, 0.0) * n.get(k, 0) for k in levels) / total)
    rows = [{"scenario": s, "mode": m, "color": c, "rate": sum(v) / len(v), "n": len(v)}
            for (s, m, c), v in per_run.items()]
    return pd.DataFrame(rows, columns=["scenario", "mode", "color", "rate", "n"])


def cost_table(runs: list[dict]) -> pd.DataFrame:
    """Mean list-price cost, tokens and LLM latency per run for the agent systems (naive and greedy cost 0)."""
    df, rows = _present(runs), []
    for scenario in SCENARIOS:
        for mode in AGENT_SYSTEMS:
            g = df[(df["scenario"] == scenario) & (df["mode"] == mode)]
            if g.empty:
                continue
            rows.append({"scenario": scenario, "mode": mode, "n": len(g), "cost_usd": float(g["est_cost_usd"].mean()),
                         "tokens": float((g["tokens_in"] + g["tokens_out"]).mean()),
                         "latency_s": float(g["llm_latency_s"].mean()), "calls": float(g["llm_calls"].mean())})
    return pd.DataFrame(rows, columns=["scenario", "mode", "n", "cost_usd", "tokens", "latency_s", "calls"])


# ───────── One-sentence takeaways (generated from the tables above) ─────────
def _pts(x: float) -> str:
    return f"{x * 100:+.1f}"


def takeaway_csr(t: pd.DataFrame, version: str) -> str:
    if t.empty:
        return f"No {version} runs saved."
    overlap, total, naive_lowest = 0, 0, True
    for scenario, g in t.groupby("scenario"):
        by = g.set_index("mode")
        close = [m for m in ("greedy", "agents", "negotiation") if m in by.index]
        if len(close) >= 2:
            total += 1
            overlap += max(by.loc[m, "ci_low"] for m in close) <= min(by.loc[m, "ci_high"] for m in close)
        if "naive" in by.index and by["mean"].idxmin() != "naive":
            naive_lowest = False
    full = t[t["mode"] != "oracle"]                  # oracle has fewer seeds, so it is not ranked here
    best = {s: full[full["scenario"] == s].sort_values("mean").iloc[-1] for s in full["scenario"].unique()}
    top = "; ".join(f"{s} {b['mode']} {b['mean']:.0%}" for s, b in best.items())
    return (f"({version}) Highest mean per scenario (full seed sets): {top}. "
            f"{'Naive is lowest everywhere. ' if naive_lowest else ''}"
            f"Greedy, agents and negotiation have overlapping 95% intervals in {overlap} of {total} scenarios.")


def takeaway_paired(t: pd.DataFrame, version: str, what: str) -> str:
    if t.empty:
        return f"({version}) {what}: no paired runs saved."
    sig = int(t["significant"].sum())
    spread = ", ".join(f"{r.scenario} {_pts(r.mean_diff)}" for r in t.itertuples())
    verdict = ("no scenario has a 95% interval that excludes zero" if sig == 0
               else f"{sig} of {len(t)} scenarios have a 95% interval that excludes zero")
    return f"({version}) {what}: mean difference in points: {spread}; {verdict}."


def takeaway_rq1(by_mode: dict[str, pd.DataFrame], version: str) -> str:
    """RQ1 in one sentence: agent systems and naive versus greedy."""
    def spread(t: pd.DataFrame) -> str:
        return ", ".join(f"{r.scenario} {_pts(r.mean_diff)}" for r in t.itertuples())
    neg, ag, naive = by_mode["negotiation"], by_mode["agents"], by_mode["naive"]
    if neg.empty:
        return f"({version}) No paired runs saved."
    return (f"({version}) Versus greedy, in points: negotiation {spread(neg)}; agents {spread(ag)}; "
            f"{int(neg['significant'].sum() + ag['significant'].sum())} of {len(neg) + len(ag)} agent comparisons exclude zero, "
            f"while naive is significantly worse in {int((naive['significant'] & (naive['mean_diff'] < 0)).sum())} of {len(naive)} scenarios.")


def takeaway_oracle(t: pd.DataFrame, version: str) -> str:
    if t.empty:
        return f"({version}) The information ablation (oracle) was run in v1 only; there are no oracle runs in {version}."
    spread = ", ".join(f"{r.scenario} {_pts(r.mean_diff)} (n={r.n})" for r in t.itertuples())
    return (f"({version}) Oracle minus negotiation, in points: {spread}; "
            f"{'no interval excludes zero' if not t['significant'].any() else 'some intervals exclude zero'}, "
            "so perfect information did not measurably help.")


def takeaway_triage(t: pd.DataFrame, version: str) -> str:
    if t.empty:
        return f"No {version} runs saved."
    m = t.groupby("color")["rate"].mean()
    return (f"({version}) Pooled over scenarios and systems, Immediate victims are served in time {m['Immediate']:.0%} of the time, "
            f"Delayed {m['Delayed']:.0%} and Minor {m['Minor']:.0%}: the sickest are the hardest to reach in time.")


def takeaway_cost(t: pd.DataFrame, version: str, vs_greedy: pd.DataFrame) -> str:
    if t.empty:
        return f"({version}) No agent runs saved."
    neg = t[t["mode"] == "negotiation"]
    cost = neg["cost_usd"].mean() if not neg.empty else t["cost_usd"].mean()
    lat = neg["latency_s"].mean() if not neg.empty else t["latency_s"].mean()
    gain = vs_greedy["mean_diff"].mean() if not vs_greedy.empty else float("nan")
    return (f"({version}) A negotiation run costs about ${cost:.3f} at list price and {lat:.0f} s of model time (naive and greedy make no model calls), "
            f"for a critical-service change of {_pts(gain)} points versus greedy (average of the scenario differences).")
