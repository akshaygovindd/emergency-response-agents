"""v3 analysis, pre-registered in docs/V3_DESIGN.md section 7. Saved results and logs only: no simulation, no API calls.

Reads  results/v2|v3/runs.jsonl and logs/v2|v3/<mode>/*.jsonl.   Writes results/analysis/09_v3_*.csv (never v1/v2/v3 data).

    python scripts/analysis_v3.py

P1 / P2 are computed by the same function (erc.eval.metrics.treatment_wait_metrics) for v2 logs and v3 logs, and the
v3 values are checked against the rows stored in results/v3. Contrasts are paired by seed within a scenario:
C1 = v3 agents minus v2 agents (effect of loans; v3 negotiation minus v2 negotiation is secondary),
C2 = v3 negotiation minus v3 agents (effect of negotiating the loans).
Confirmatory family: P1 and P2 x surge x {C1, C2 on agents} = 4 tests, Holm-corrected on the exact sign-flip p-values.
Everything else is exploratory.
"""
from __future__ import annotations

import itertools
import json
from collections import Counter

import numpy as np
import pandas as pd

from erc.config import LOG_DIR, RESULTS_DIR, SCENARIO_DIR, Mode, ScenarioName
from erc.eval.experiment import load_runs, load_scenario
from erc.eval.metrics import treatment_wait_metrics
from erc.eval.stats import paired_comparison, summarize
from erc.logging.event_log import EventLog
from erc.models.state import SimulationState

OUT = RESULTS_DIR / "analysis"
SCENARIOS = ("surge", "bottleneck")
MODES = ("agents", "negotiation")
METRICS = {"P1": "critical_treated_within_n_rate", "P2": "critical_treatment_wait_mean",
           "never_started": "critical_never_started", "CSR": "critical_service_rate",
           "treatment_started_rate": "treatment_started_rate"}
CONFIRMATORY = [("P1", "surge", "C1"), ("P2", "surge", "C1"), ("P1", "surge", "C2"), ("P2", "surge", "C2")]


def log_of(version: str, mode: str, scenario: str, seed: int) -> EventLog:
    return EventLog.load(LOG_DIR / version / mode / f"{scenario}_seed{seed}_{mode}.jsonl")


def sign_flip_p(diffs: list[float]) -> float:
    """Exact two-sided paired sign-flip permutation p-value (all 2^n sign patterns)."""
    d = np.array([x for x in diffs if x is not None], dtype=float)
    if d.size == 0 or not d.any():
        return 1.0
    obs = abs(d.sum())
    signs = np.array(list(itertools.product((-1, 1), repeat=d.size)))
    return float(np.mean(np.abs(signs @ d) >= obs - 1e-12))


def holm(ps: list[float]) -> list[float]:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, running = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(ps) - rank) * ps[i]))
        adj[i] = running
    return adj


# ───────────────────────── Per-run table (v2 and v3 measured alike) ─────────────────────────
def run_table() -> pd.DataFrame:
    rows = []
    for version in ("v2", "v3"):
        stored = {(r["scenario"], r["seed"], r["mode"]): r for r in load_runs(version)}
        for scn, mode in itertools.product(SCENARIOS, MODES):
            for (sc, seed, m), row in sorted(stored.items()):
                if sc != scn or m != mode:
                    continue
                state = SimulationState.from_scenario(load_scenario(ScenarioName(scn), seed))
                state.time_min = 120
                log = log_of(version, mode, scn, seed)
                rec = {"version": version, "scenario": scn, "seed": seed, "mode": mode, "n_critical": row["n_critical"],
                       **treatment_wait_metrics(state, log)}
                for n in (5, 15):
                    rec[f"P1_N{n}"] = treatment_wait_metrics(state, log, n)["critical_treated_within_n_rate"]
                for key in ("critical_service_rate", "treatment_started_rate", "tokens_in", "tokens_out", "fresh_tokens",
                            "est_cost_usd", "llm_calls", "critical_unserved"):
                    rec[key] = row[key]
                if version == "v3":
                    for key in ("critical_treated_within_n_rate", "critical_treatment_wait_mean", "critical_never_started"):
                        stored_v = row[key]
                        assert (stored_v is None and rec[key] is None) or abs(stored_v - rec[key]) < 1e-9, (scn, seed, mode, key)
                    rec.update({k: row[k] for k in row if k.startswith("loan")})
                rows.append(rec)
    return pd.DataFrame(rows)


# ───────────────────────── Contrasts ─────────────────────────
def contrast(df: pd.DataFrame, scenario: str, label: str, metric: str, a: tuple[str, str], b: tuple[str, str],
             drop_seed: int | None = None) -> dict:
    def series(version: str, mode: str) -> pd.Series:
        g = df[(df.version == version) & (df.scenario == scenario) & (df["mode"] == mode)].set_index("seed")[metric]
        return g
    sa, sb = series(*a), series(*b)
    seeds = sorted(s for s in set(sa.index) & set(sb.index) if s != drop_seed)
    pairs = [(sa[s], sb[s]) for s in seeds if pd.notna(sa[s]) and pd.notna(sb[s])]
    c = paired_comparison([float(x) for x, _ in pairs], [float(y) for _, y in pairs])
    diffs = [float(x) - float(y) for x, y in pairs]
    return {"contrast": label, "scenario": scenario, "metric": metric, "pairs": c.n,
            "mean_a": float(np.mean([x for x, _ in pairs])) if pairs else None,
            "mean_b": float(np.mean([y for _, y in pairs])) if pairs else None,
            "mean_diff": c.mean_diff, "ci_low": c.ci_low, "ci_high": c.ci_high,
            "wins/losses/ties": f"{c.wins}/{c.losses}/{c.ties}", "ci_excludes_zero": c.significant,
            "perm_p": sign_flip_p(diffs)}


def contrast_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for scn in SCENARIOS:
        for key, metric in METRICS.items():
            specs = [("C1 agents (v3 - v2)", ("v3", "agents"), ("v2", "agents")),
                     ("C1b negotiation (v3 - v2)", ("v3", "negotiation"), ("v2", "negotiation")),
                     ("C2 negotiation - agents (v3)", ("v3", "negotiation"), ("v3", "agents"))]
            for label, a, b in specs:
                rows.append({**contrast(df, scn, label, metric, a, b), "metric_name": key})
    table = pd.DataFrame(rows)
    # Holm over the registered confirmatory family
    table["confirmatory"] = False
    table["holm_p"] = np.nan
    fam = []
    for key, scn, c in CONFIRMATORY:
        label = "C1 agents (v3 - v2)" if c == "C1" else "C2 negotiation - agents (v3)"
        fam.append(table[(table.metric_name == key) & (table.scenario == scn) & (table.contrast == label)].index[0])
    for i, p in zip(fam, holm([table.loc[i, "perm_p"] for i in fam])):
        table.loc[i, "confirmatory"], table.loc[i, "holm_p"] = True, p
    sens = []
    for scn in SCENARIOS:
        for metric, name in (("critical_treated_within_n_rate", "P1 N=10, without seed 42"), ("P1_N5", "P1 N=5"), ("P1_N15", "P1 N=15")):
            for label, a, b in [("C1 agents (v3 - v2)", ("v3", "agents"), ("v2", "agents")),
                                ("C2 negotiation - agents (v3)", ("v3", "negotiation"), ("v3", "agents"))]:
                sens.append({**contrast(df, scn, label, metric, a, b, drop_seed=42 if "seed 42" in name else None), "metric_name": name})
        for label, a, b in [("C1 agents (v3 - v2)", ("v3", "agents"), ("v2", "agents")),
                            ("C2 negotiation - agents (v3)", ("v3", "negotiation"), ("v3", "agents"))]:
            sens.append({**contrast(df, scn, label, "critical_treatment_wait_mean", a, b, drop_seed=42), "metric_name": "P2 without seed 42"})
    return table, pd.DataFrame(sens)


def level_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (version, scn, mode), g in df.groupby(["version", "scenario", "mode"]):
        rec = {"version": version, "scenario": scn, "mode": mode, "runs": len(g)}
        for key, metric in METRICS.items():
            s = summarize([None if pd.isna(x) else float(x) for x in g[metric]])
            rec[f"{key}_mean"], rec[f"{key}_ci_low"], rec[f"{key}_ci_high"] = s.mean, s.ci_low, s.ci_high
        rec["critical_handed_over_mean"] = g["critical_handed_over"].mean()
        rec["critical_never_started_total"] = int(g["critical_never_started"].sum())
        rec["n_critical_total"] = int(g["n_critical"].sum())
        rows.append(rec)
    return pd.DataFrame(rows)


# ───────────────────────── Loans ─────────────────────────
def loan_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    v3 = df[df.version == "v3"]
    cols = ["loan_requests", "loans_accepted", "loans_rejected", "loans_countered", "loan_counters_accepted", "loans_arbitrated",
            "loan_fallbacks", "loan_redirects", "loans_executed", "loan_team_minutes"]
    summary = v3.groupby(["scenario", "mode"])[cols].agg(["sum", "mean"]).round(2)
    summary.columns = [f"{a}_{b}" for a, b in summary.columns]
    summary = summary.reset_index()
    summary.insert(2, "runs", v3.groupby(["scenario", "mode"]).size().values)
    summary["runs_with_a_loan"] = v3.assign(any=v3.loans_executed > 0).groupby(["scenario", "mode"])["any"].sum().values
    pairs, timing, refused = Counter(), [], Counter()
    for _, r in v3.iterrows():
        ev = log_of("v3", r["mode"], r["scenario"], r["seed"]).events
        refused[(r["scenario"], r["mode"])] += sum(e["kind"] == "action_rejected" and e["action"]["action_type"] == "loan_staff" for e in ev)
        started = [e for e in ev if e["kind"] == "loan_started"]
        by_id = {}
        for e in ev:
            if e["kind"] in ("loan_arrived", "loan_recalled", "loan_returned"):
                by_id.setdefault(e["loan_id"], {})[e["kind"]] = e["t"]
        for e in started:
            pairs[(r["scenario"], r["mode"], f"{e['lender_id']} -> {e['borrower_id']}", e["capability"])] += e["teams"]
            t = by_id.get(e["loan_id"], {})
            arrived = t.get("loan_arrived", e["arrive_min"])
            recalled = t.get("loan_recalled", 120)
            timing.append({"scenario": r["scenario"], "mode": r["mode"], "seed": r["seed"],
                           "teams": e["teams"], "planned_min": e["ends_min"] - e["arrive_min"],
                           "capacity_minutes": e["teams"] * max(0, min(recalled, 120) - min(arrived, 120)),
                           "away_minutes": e["teams"] * (min(t.get("loan_returned", 120), 120) - e["t"])})
    summary["rejected_at_execution"] = [refused[(r.scenario, r["mode"])] for _, r in summary.iterrows()]
    pair_df = pd.DataFrame([{"scenario": s, "mode": m, "pair": p, "care": c, "teams": n} for (s, m, p, c), n in sorted(pairs.items())])
    t = pd.DataFrame(timing)
    cap = t.groupby(["scenario", "mode"])[["teams", "planned_min", "capacity_minutes", "away_minutes"]].sum().reset_index() if len(t) else t
    return summary, pair_df, cap


def divergence_table(df: pd.DataFrame) -> pd.DataFrame:
    """v3 run versus the v2 run of the same system, scenario and seed: when did they first differ?"""
    rows = []
    for _, r in df[df.version == "v3"].iterrows():
        a = [json.dumps(e["action"], sort_keys=True) for e in log_of("v2", r["mode"], r["scenario"], r["seed"]).events
             if e["kind"] == "action_accepted"]
        ev = log_of("v3", r["mode"], r["scenario"], r["seed"]).events
        loans = [e for e in ev if e["kind"] == "loan_started"]
        accepted = [e for e in ev if e["kind"] == "action_accepted"]
        old = [e for e in log_of("v2", r["mode"], r["scenario"], r["seed"]).events if e["kind"] == "action_accepted"]
        first_diff = next((x["t"] for x, y in itertools.zip_longest(accepted, old) if x is None or y is None
                           or json.dumps(x["action"], sort_keys=True) != json.dumps(y["action"], sort_keys=True)), None)
        rows.append({"scenario": r["scenario"], "seed": r["seed"], "mode": r["mode"], "loans": len(loans),
                     "first_loan_min": loans[0]["t"] if loans else None, "first_divergence_min": first_diff,
                     "identical_to_v2": first_diff is None})
    return pd.DataFrame(rows)


def cost_table(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["version", "scenario", "mode"])[["tokens_in", "tokens_out", "fresh_tokens", "est_cost_usd", "llm_calls"]].mean().round(3)
    g["logical_tokens"] = g.tokens_in + g.tokens_out
    return g.reset_index()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = run_table()
    contrasts, sens = contrast_tables(df)
    summary, pairs, cap = loan_tables(df)
    tables = {"09_v3_runs": df, "09_v3_levels": level_table(df), "09_v3_contrasts": contrasts, "09_v3_sensitivity": sens,
              "09_v3_loans": summary, "09_v3_loan_pairs": pairs, "09_v3_loan_capacity": cap,
              "09_v3_divergence": divergence_table(df), "09_v3_cost": cost_table(df)}
    for name, t in tables.items():
        t.to_csv(OUT / f"{name}.csv", index=False)
        print(f"wrote {name}.csv ({len(t)} rows)")


if __name__ == "__main__":
    main()
