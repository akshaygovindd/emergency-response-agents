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
from erc.eval.experiment import load_runs, paired_table, run_experiment, summary_table


def main() -> None:
    load_dotenv()   # reads OPENAI_API_KEY from .env (needed for agent modes)
    parser = argparse.ArgumentParser(description="Run emergency-coordination experiments.")
    parser.add_argument("--mode", nargs="+", choices=[m.value for m in Mode],
                        help="Systems to run. Omit to only print saved results.")
    parser.add_argument("--scenario", nargs="+", choices=[s.value for s in ScenarioName],
                        default=[s.value for s in ScenarioName])
    parser.add_argument("--seed", type=int, nargs="+", help="Specific seeds (default: all for each scenario)")
    args = parser.parse_args()

    if args.mode:
        run_experiment([Mode(m) for m in args.mode], [ScenarioName(s) for s in args.scenario], args.seed)

    runs = load_runs()
    if not runs:
        print("No runs saved yet. Try: python scripts/run.py --mode naive greedy")
        return

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    pd.set_option("display.float_format", "{:.2f}".format)
    summary, paired = summary_table(runs), paired_table(runs)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(RESULTS_DIR / "summary.csv", index=False)
    paired.to_csv(RESULTS_DIR / "paired_vs_greedy.csv", index=False)

    print("\n=== Summary: mean across seeds ===")
    print(summary.to_string(index=False))
    if not paired.empty:
        print("\n=== Paired comparison vs greedy: critical service rate ===")
        print(paired.to_string(index=False))


if __name__ == "__main__":
    main()