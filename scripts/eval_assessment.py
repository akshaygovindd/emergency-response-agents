"""Measure the Assessment Agent's extraction accuracy against ground truth.

Usage:
    python scripts/eval_assessment.py --scenario bottleneck --seed 42 --version v2   # 10 incidents
    python scripts/eval_assessment.py --version v2                         # all 420 incidents
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter

from dotenv import load_dotenv

from erc.agents.assessment import ASSESSMENT_AGENT, score, to_report
from erc.agents.llm_cache import run_cached
from erc.config import KNOWN_VERSIONS, SCENARIO_DIR, ScenarioName, require_writable, results_dir, seeds_for
from erc.models.state import Scenario
from erc.scenarios.descriptions import load_descriptions


async def _assess(name, seed, incident, text, sem):
    async with sem:
        return name, seed, incident, await run_cached(ASSESSMENT_AGENT, f"Dispatch report:\n{text}")


async def main(names: list[ScenarioName], seeds: list[int] | None, version: str) -> None:
    sem, jobs = asyncio.Semaphore(8), []
    for name in names:
        for seed in (seeds or seeds_for(name)):
            scenario = Scenario.load(SCENARIO_DIR / f"{name.value}_seed{seed}.json")
            reports = load_descriptions(name, seed)
            jobs += [_assess(name, seed, i, reports[i.incident_id], sem) for i in scenario.incidents]
    results = await asyncio.gather(*jobs)

    totals, errors, cost = Counter(), [], Counter()
    for name, seed, incident, res in results:
        cost.update(calls=1, hits=int(res.cache_hit), tokens_in=res.tokens_in, tokens_out=res.tokens_out)
        report = to_report(incident, res.output)
        s = score(incident, report)
        totals.update(s)
        if s["severity_exact"] < s["victims_true"] or s["capability_correct"] < s["victims_true"] \
                or not s["responder_correct"] or not s["count_correct"]:
            errors.append({
                "scenario": name.value, "seed": seed, "incident": incident.incident_id,
                "truth": [(int(v.severity), v.required_capability.value) for v in incident.victims],
                "assessed": [(int(v.severity), v.required_capability.value) for v in report.victims],
                "responder_truth": getattr(incident.required_responder, "value", None),
                "responder_assessed": getattr(report.required_responder, "value", None),
            })

    n_v, n_i = totals["victims_true"], totals["incidents"]
    rates = {
        "incidents": n_i, "victims": n_v,
        "victim_count_correct": totals["count_correct"] / n_i,
        "severity_exact": totals["severity_exact"] / n_v,
        "severity_within_1": totals["severity_within1"] / n_v,
        "critical_flag_correct": totals["critical_correct"] / n_v,
        "care_type_correct": totals["capability_correct"] / n_v,
        "als_correct": totals["als_correct"] / n_v,
        "team_needed_correct": totals["responder_correct"] / n_i,
    }
    print("\n=== Assessment accuracy ===")
    for k, v in rates.items():
        print(f"  {k:24} {v:.1%}" if isinstance(v, float) else f"  {k:24} {v}")
    print(f"\nLLM calls: {cost['calls']} (cache hits {cost['hits']}) | "
          f"tokens in {cost['tokens_in']} | tokens out {cost['tokens_out']}")
    print(f"Incidents with at least one error: {len(errors)}")
    results_dir(version).mkdir(parents=True, exist_ok=True)
    (results_dir(version) / "assessment_accuracy.json").write_text(
        json.dumps({"rates": rates, "cost": dict(cost), "errors": errors}, indent=2))


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", nargs="+", choices=[s.value for s in ScenarioName],
                        default=[s.value for s in ScenarioName])
    parser.add_argument("--seed", type=int, nargs="+")
    parser.add_argument("--version", choices=KNOWN_VERSIONS, required=True)
    parser.add_argument("--allow-v1-write", action="store_true")
    args = parser.parse_args()
    try:
        require_writable(args.version, args.allow_v1_write)
    except PermissionError as e:
        parser.error(str(e))
    asyncio.run(main([ScenarioName(s) for s in args.scenario], args.seed, args.version))