# Experiment log

## 2026-10-28: completing the original v1 design (v1, not v2)

The v1 pilot was frozen with only part of its design finished. These runs fill the missing cells
so v1 matches the original plan; they are v1 runs, not v2.

- bottleneck, agents and negotiation, seeds 43-46 (seed 42 was already done)
- oracle ablation, normal and surge, seeds 42-44

**Why `--allow-v1-write` was used.** v1 is write-protected, so the runner refuses to write
`results/v1/` or `logs/v1/` without this flag. The flag is needed here because these are new v1
rows, and the commands are scoped so that no existing v1 row or log is touched:

- Results are upserted by `(scenario, seed, mode)`. Every requested key is absent from
  `results/v1/runs.jsonl`, so the existing rows are loaded and written back unchanged.
- Each run writes its own log file `logs/v1/<mode>/<scenario>_seed<N>_<mode>.jsonl`. None of the
  requested files exist yet, and seed 42 is excluded for bottleneck agents and negotiation.
- Agent models, prompts, tools, scenarios and the environment are unchanged (`agents-frozen`).
- With the flag, `scripts/run.py` also regenerates the summary CSVs in `results/v1/`
  (derived tables only, recomputed from `runs.jsonl`); they will now include the new rows.

## 2026-10-28: v2 frozen (tag `v2-frozen`)

v2 adds hospital admission negotiation (see `docs/V2_DESIGN.md`): Dispatch requests a destination,
Hospital Coordination accepts, rejects, or counters (whole load), up to 3 rounds, then Resource
Allocation, then the nearest-capable-hospital rule. It is enabled only for `--version v2`; v1 code
paths, prompts, and the naive and greedy baselines are unchanged (a test checks baselines are identical).
v2 grid: agents and negotiation on normal, surge, bottleneck (no oracle; v1 covers that ablation).

Dev-seed runs (agents and negotiation, seed 42, `--version v2`; written to `results/v2/` and `logs/v2/`):
- normal 42: critical service rate 0.82 / 0.82 (v1: 0.64 / 0.82); 0 invalid proposals.
- bottleneck 42: 0.18 / 0.18 (v1: 0.18 / 0.18); 0 invalid proposals.
- surge 42: 0.32 / 0.32 (v1: 0.21 / 0.25); 6 invalid proposals each, refused by the tool and retried.
- Fresh tokens: 25.4k / 7.5k (bottleneck), 47.8k / 39.7k (normal), 101k / 16k (surge).

Findings and the decision to freeze without prompt changes are in `docs/V2_DESIGN.md` section 15.
The full v2 grid has not been run.
