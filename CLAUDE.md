# CLAUDE.md: Project briefing for Claude Code

## Project
CSYE7380 midterm (Prof. Das), due **Nov 4, 2026, 6pm**.
**Negotiation-based multi-agent emergency resource coordination**, built with the
OpenAI Agents SDK (agents) + Streamlit/Plotly (dashboard, to build).

Central question: when emergency resources are contested, do autonomous agents that
communicate and negotiate outperform strong rule-based allocation?

Core rule: **Agents propose. Python owns reality, detects conflicts, validates, executes.**

## Execution plan
**PLAN.md is the authoritative execution plan** (scope, schedule, checkpoints, rules). Read it at the
start of every session. If this file and PLAN.md disagree, PLAN.md wins; the "Plan (remaining)"
list below is the older, v1-era summary.

## Environment (frozen)
- 20 x 20 km grid, 120-min runs (arrivals in first 75 min, then drain), 1-min steps
- 3 hospitals: H-T Trauma Center, H-B Burn Unit, H-G General
- 5 ambulances (2 ALS), 3 responder teams (fire, rescue, medical), 6 doctors, 12 nurses
- Scenarios: normal (12 incidents, seeds 42-51), surge (25 incidents, seeds 42-51),
  bottleneck (10 incidents in 20 min, 2 ambulances, trauma half full, seeds 42-46).
  Oracle ablation: normal + surge, seeds 42-44.
- Severity 1-5 per victim (4-5 = critical). Deadline = minutes to first medical contact.
- Primary metric: critical victim service rate (critical victims contacted within deadline).

## Systems compared
naive, greedy (baselines), agents (no negotiation, fixed priority rule),
negotiation (Resource Allocation LLM, counter-proposals, max 3 rounds, fallback),
oracle (negotiation with ground-truth assessments; ablation only).

## Code map
- `src/erc/config.py` all settings (agent model: gpt-5.4-mini, do NOT change)
- `src/erc/models/` entities, messages, state (Pydantic)
- `src/erc/scenarios/` generator.py (seeded), descriptions.py (LLM 911 reports, cached)
- `src/erc/sim/` engine, validator, travel, deterioration
- `src/erc/policies/` naive, greedy
- `src/erc/agents/` assessment, agents (dispatch, hospital), tools, prompts, conflicts,
  system (AgentSystem), negotiation (NegotiatingSystem), llm_cache
- `src/erc/eval/` metrics, stats, experiment
- `scripts/run.py` experiments CLI, `scripts/trace.py` readable run log
- `data/scenarios/`, `data/descriptions/`, `data/llm_cache/` (committed)
- `logs/<version>/<mode>/<scenario>_seed<N>_<mode>.jsonl` event logs, `results/<version>/runs.jsonl` metrics
  (v1 = frozen pilot, write-protected; v2 runs need `--version v2`)

## Commands
- Activate: `source .venv/bin/activate`
- Tests: `pytest -q` (111 passing at agents-frozen)
- Print saved results (free): `python scripts/run.py` (v1) or `python scripts/run.py --version v2`
- Experiments (USE OPENAI TOKENS): `python scripts/run.py --mode ... --scenario ... --seed ... --version v2`
- Trace a run: `python scripts/trace.py logs/v1/negotiation/normal_seed42_negotiation.jsonl`

## Hard rules
1. **Never run agent experiments (modes agents, negotiation, oracle) or anything that calls
   the OpenAI API without explicit permission.** Free daily allowance is ~2.5M tokens.
   Cached reruns are free, but ask anyway.
2. **Never open, print, or commit `.env`.**
3. **Do not change agent prompts, tools, the environment, or scenario data.** Tags
   `calibration-frozen`, `environment-frozen`, `agents-frozen` mark the frozen experiment.
   Dashboard and analysis code may be added freely.
4. Run `pytest -q` after every change; all tests must pass before committing.
5. Small, focused commits with clear messages. Push only when asked.
6. Explain each change briefly in plain language (the student must be able to present it).
7. Prefer extending over rewriting; keep the existing style (typed, small functions, OOP).

8. **No existing v1 result or log may be overwritten, transformed in place, or regenerated under a v2
   path.** The one-time `"version": "v1"` migration of `results/v1/runs.jsonl` is the only exception.
9. **Every v2 run must explicitly declare version v2** (`--version v2`). Never mix v1 and v2 rows in one
   table without the `version` column.
10. **Every claim in slides or the README must trace to a number in `results/<version>/`.**

## Plan (remaining)
1. Finish remaining experiment runs (only with permission, split by daily token budget).
2. **Replay dashboard (top priority):** Prof. Das wants the final presentation to OPEN with it:
   pick a scenario + run number (run 1-10 = seed 42-51) + system, press play, and watch
   incidents appear (START triage colors), ambulances move, agent messages stream
   (proposal, conflict, counter-proposal, accept/reject, commit), hospitals fill, and live
   KPIs update. Plus a side-by-side greedy vs agents view. Replays saved runs from logs
   (no API calls). Ambulance positions per minute may need to be added to snapshot events;
   regenerate logs via cached reruns (zero tokens) only with permission.
3. START triage colors: severity 4-5 Immediate (red), 3 Delayed (yellow), 1-2 Minor (green),
   Expectant (black) = critical victim not reached by deadline (display/analysis only).
4. Contention numbers + scenario map per scenario (analysis only, no simulation change).
5. Optional: Excel export of one scenario (one sheet per entity).
6. Future work only (not now): hospital accept/reject/counter, staff sharing between hospitals.
