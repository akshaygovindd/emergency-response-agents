"""Command-line entry point for experiments.

Examples:
    python scripts/run.py --mode naive greedy --version v2           # all scenarios, all seeds
    python scripts/run.py --mode greedy --scenario bottleneck --seed 42 --version v2
    python scripts/run.py                                            # just print saved v1 results
    python scripts/run.py --version v2                               # just print saved v2 results

Running any mode requires an explicit --version. v1 is frozen: writing it needs --allow-v1-write.
"""
from __future__ import annotations

import argparse

import pandas as pd
from dotenv import load_dotenv

from erc.config import KNOWN_VERSIONS, PRINT_VERSION, PROTECTED_VERSIONS, Mode, ScenarioName, require_writable, results_dir
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
    parser.add_argument("--version", choices=KNOWN_VERSIONS,
                        help=f"Experiment version. Required with --mode; printing defaults to {PRINT_VERSION}.")
    parser.add_argument("--allow-v1-write", action="store_true",
                        help="Allow writing results/logs for the frozen v1 (almost never wanted).")
    args = parser.parse_args()
    if args.mode and not args.version:
        parser.error("--version is required when running a mode (e.g. --version v2)")
    version = args.version or PRINT_VERSION
    if args.mode:
        try:
            require_writable(version, args.allow_v1_write)
        except PermissionError as e:
            parser.error(str(e))

    fresh = None
    if args.mode:
        new_runs = run_experiment([Mode(m) for m in args.mode], [ScenarioName(s) for s in args.scenario],
                                  args.seed, version=version, allow_v1_write=args.allow_v1_write)
        fresh = sum(m.fresh_tokens for m in new_runs)

    runs = load_runs(version)
    if not runs:
        print(f"No {version} runs saved yet. Try: python scripts/run.py --mode naive greedy --version {version}")
        return

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    pd.set_option("display.float_format", "{:.2f}".format)
    summary, coordination = summary_table(runs), coordination_table(runs)
    vs_greedy = paired_table(runs, baseline="greedy")                       # RQ1
    rq2 = only(paired_table(runs, baseline="agents"), "negotiation")        # RQ2
    ablation = only(paired_table(runs, baseline="negotiation"), "oracle")   # information ablation

    if version in PROTECTED_VERSIONS and not args.allow_v1_write:
        print(f"({version} is frozen: printing only, CSV files in results/{version}/ left untouched)")
    else:
        out = results_dir(version)
        out.mkdir(parents=True, exist_ok=True)
        summary.to_csv(out / "summary.csv", index=False)
        coordination.to_csv(out / "coordination.csv", index=False)
        vs_greedy.to_csv(out / "paired_vs_greedy.csv", index=False)
        rq2.to_csv(out / "paired_negotiation_vs_agents.csv", index=False)
        ablation.to_csv(out / "paired_oracle_vs_negotiation.csv", index=False)

    print(f"\n=== Summary ({version}): mean across seeds ===")
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