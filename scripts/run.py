"""Command-line entry point for experiments.

Examples:
    python scripts/run.py --mode naive greedy                        # all scenarios, all seeds
    python scripts/run.py --mode greedy --scenario bottleneck --seed 42
    python scripts/run.py                                            # just print saved results
"""
from __future__ import annotations

import argparse

import pandas as pd
from dotenv import load_dotenv

from erc.config import RESULTS_DIR, Mode, ScenarioName
from erc.eval.experiment import coordination_table, load_runs, paired_table, run_experiment, summary_table


def only(table: pd.DataFrame, mode: str) -> pd.DataFrame:
    return table[table["mode"] == mode] if not table.empty else table


def main() -> None:
    load_dotenv()   # reads OPENAI_API_KEY from .env (needed for agent modes)
    parser = argparse.ArgumentParser(description="Run emergency-coordination experiments.")
    parser.add_argument("--mode", nargs="+", choices=[m.value for m in Mode],
                        help="Systems to run. Omit to only print saved results.")
    parser.add_argument("--scenario", nargs="+", choices=[s.value for s in ScenarioName],
                        default=[s.value for s in ScenarioName])
    parser.add_argument("--seed", type=int, nargs="+", help="Specific seeds (default: all for each scenario)")
    args = parser.parse_args()

    fresh = None
    if args.mode:
        new_runs = run_experiment([Mode(m) for m in args.mode], [ScenarioName(s) for s in args.scenario], args.seed)
        fresh = sum(m.fresh_tokens for m in new_runs)

    runs = load_runs()
    if not runs:
        print("No runs saved yet. Try: python scripts/run.py --mode naive greedy")
        return

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    pd.set_option("display.float_format", "{:.2f}".format)
    summary, coordination = summary_table(runs), coordination_table(runs)
    vs_greedy = paired_table(runs, baseline="greedy")                       # RQ1
    rq2 = only(paired_table(runs, baseline="agents"), "negotiation")        # RQ2
    ablation = only(paired_table(runs, baseline="negotiation"), "oracle")   # information ablation

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(RESULTS_DIR / "summary.csv", index=False)
    coordination.to_csv(RESULTS_DIR / "coordination.csv", index=False)
    vs_greedy.to_csv(RESULTS_DIR / "paired_vs_greedy.csv", index=False)
    rq2.to_csv(RESULTS_DIR / "paired_negotiation_vs_agents.csv", index=False)
    ablation.to_csv(RESULTS_DIR / "paired_oracle_vs_negotiation.csv", index=False)

    print("\n=== Summary: mean across seeds ===")
    print(summary.to_string(index=False))
    if not coordination.empty:
        print("\n=== Agent coordination and cost: mean per run ===")
        print(coordination.to_string(index=False))
    for title, table in (("RQ1, paired vs greedy", vs_greedy),
                         ("RQ2, negotiation vs no negotiation", rq2),
                         ("Ablation, oracle vs text-based negotiation", ablation)):
        if not table.empty:
            print(f"\n=== {title}: critical service rate ===")
            print(table.to_string(index=False))
    if fresh is not None:
        print(f"\nFresh (uncached) tokens used by this command: {fresh:,}")


if __name__ == "__main__":
    main()