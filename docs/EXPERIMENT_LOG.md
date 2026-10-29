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
