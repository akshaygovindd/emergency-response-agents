# Simulation Assumptions

This is a **resource allocation simulation**, not a medical model and not medical advice. All data is synthetic. Every number below lives in `src/erc/config.py` or `src/erc/scenarios/generator.py`. Environment settings were frozen before any agent was run (Git tags `calibration-frozen` and `environment-frozen`).

## 1. Space and time

- Synthetic 20 × 20 km grid (not a real map). Distance is Manhattan distance (grid streets).
- One-minute time steps. Incidents arrive during the first 75 minutes (20 in the bottleneck scenario); the run continues to minute 120 as a **drain period**, so victims arriving late still have a fair chance to be reached.
- Nobody sees the future: only incidents that have already arrived are visible to any system.

## 2. Fixed infrastructure (identical for every seed)

| Hospital | Location | ER capacity | Treatment slots | Beds |
|---|---|---|---|---|
| H-T Trauma Center | (5, 15) | 6 | trauma 3, general 1 | 10 |
| H-B Burn Unit | (15, 13) | 5 | burn 3, general 1 | 8 |
| H-G General Hospital | (10, 4) | 8 | general 4, trauma 1 | 14 |

- **Staff:** each hospital has 2 doctors (expert in the specialty, intermediate in a secondary area, basic otherwise; max 3 patients) and 4 nurses (intermediate in the specialty, basic otherwise; max 2 patients). Secondary areas: H-T general, H-B general, H-G trauma.
- **Ambulances:** 5 units with capacity 2. AMB-01 and AMB-03 are advanced life support (ALS); AMB-02, AMB-04, AMB-05 are basic (BLS). After handover, an ambulance becomes available at the hospital (no return trip to base).
- **Responder teams:** FIRE-1, RESCUE-1, MED-1. A team stays at an incident until no victim there is still waiting.

## 3. Incidents and victims (random per seed, reproducible)

| Incident type | Probability | Specialty | Responder needed | Victims |
|---|---|---|---|---|
| Vehicle collision | 0.35 | trauma | rescue | 1 to 4 |
| Building fire | 0.20 | burn | fire | 1 to 5 |
| Structural collapse | 0.10 | trauma | rescue | 2 to 5 |
| Industrial accident | 0.10 | burn | fire | 1 to 3 |
| Medical emergency | 0.25 | general | none | 1 |

- Severity (1 to 5) is drawn per victim from the scenario's severity weights.
- Victims of severity 3 or higher need the incident's specialty with probability 0.8, otherwise general care. Severity 1 to 2 always need general care.
- **Critical** = severity 4 or 5. Critical victims need ALS.
- **Deadline** (minutes from incident arrival to first medical contact): severity 5: 8 to 15, severity 4: 15 to 25, severity 3: 25 to 40, severity 2: 40 to 60, severity 1: 60 to 90.
- Locations are uniform within the grid (0.5 to 19.5 km).

## 4. Scenarios

| Scenario | Incidents | Arrival window | Severity weights (1 to 5) | Seeds | Special conditions |
|---|---|---|---|---|---|
| Normal | 12 | 75 min | .20 .25 .25 .18 .12 | 42 to 51 | none |
| Surge | 25 | 75 min | .15 .20 .25 .22 .18 | 42 to 51 | none |
| Bottleneck | 10 | 20 min | .05 .10 .15 .30 .40 | 42 to 46 | only AMB-01 (ALS) and AMB-02 (BLS) in service; 2 of 3 trauma slots and 2 beds at H-T occupied for the whole run |

The oracle ablation uses seeds 42 to 44 of normal and surge. The bottleneck scenario is a qualitative stress test, not a basis for aggregate statistical claims.

## 5. Travel

- Ambulance speed 60 km/h (1 km per minute before traffic).
- Traffic factor between 0.8 and 1.5, computed deterministically from (seed, origin cell, destination cell, 15-minute window). The same trip at the same time takes the same time under every system.
- Travel time = ceil(distance × traffic factor), minimum 1 minute.
- 5 minutes on scene to load patients; 5 minutes for handover at the hospital.
- If an incident needs a rescue or fire team and none is on scene, loading takes 15 extra minutes (extrication).

## 6. Patient deterioration (synthetic)

- Condition starts at 100. Without care, each victim loses condition at a constant rate calibrated to reach the critical threshold of 40 exactly at their deadline: rate = 60 / deadline per minute.
- Once a crew is with the victim, decline is multiplied by a care factor: ALS crew 0.1, BLS crew 0.5, medical team on scene 0.5, waiting in an ER 0.1. Decline stops when treatment starts.
- Before first contact nobody receives care, so condition at contact is computed exactly.

## 7. Treatment

- Treatment starts only when there is a free slot for the needed capability, a free bed, a doctor with at least intermediate skill in that capability, and a nurse with at least basic skill, all with spare workload.
- ER queue order: highest severity first, then lowest condition.
- Duration by severity: 15, 20, 30, 45, 60 minutes. Beds stay occupied after treatment (admitted patients).

## 8. Validation rules (enforced in one place, `sim/validator.py`)

An action is rejected, with a reason code, if: the incident has not arrived; a resource does not exist or is busy; the ambulance would exceed capacity; a victim is already assigned or not part of the incident; **no hospital can treat the whole ambulance load together**; the hospital lacks the needed capability; the ER would exceed capacity counting patients already on the way; or the admission breaks routing (one ambulance goes to one hospital, no changes once transporting).

BLS ambulances may carry ALS-needing victims; this is allowed and penalised through slower care, not rejected.

## 9. Decision frequency

A system is consulted only when the decision situation changes (new waiting victims with free ambulances, a loaded ambulance without a destination, a needed responder available, or a change in ER load). This keeps runs efficient and limits API calls for agent systems.

## 10. Metrics

- **Primary: critical service rate** = share of critical victims whose first medical contact happened within their deadline.
- Response time = minutes from incident arrival to first medical contact (mean, median, P95, and critical-only mean).
- Contacted, hospitalised, and treatment-started rates; service rate by severity; condition at contact for critical victims; number of deteriorated victims.
- Ambulance and responder utilisation (share of busy minutes); ER-full events.
- Accepted and rejected actions with reasons; for agents also messages, negotiations, counter-proposals, rounds, LLM calls, tokens, and latency.

## 11. Statistics

- Every system runs on identical scenario files and seeds.
- Summaries report mean, standard deviation, median, P95, and a 95% confidence interval (Student's t, conservative degrees of freedom).
- Systems are compared with **paired, seed-by-seed differences**; a difference is called significant when its 95% confidence interval excludes zero.

## 12. Information and fairness

- Baselines read ground-truth incident attributes. The agents must infer them from LLM-written text reports. This deliberately disadvantages the agents; extraction accuracy is reported, and the oracle ablation (agents given ground truth) measures its effect.
- The greedy baseline and the agents estimate travel from distance only; neither sees traffic in advance.

## 13. Scope decisions

- Hospital-to-hospital staff transfer is outside the simulation scope. Hospital coordination means admission, diversion, destination selection, and treatment-capacity negotiation.
- Out-of-service ambulances are removed from the bottleneck scenario rather than modelled as a status.
- Pre-occupied trauma slots in the bottleneck scenario stay occupied for the whole run.

## 14. LLM settings (agent systems)

- **Model: `gpt-5.4-mini`** (`SETTINGS.llm.model` in `src/erc/config.py`, overridable with `ERC_MODEL`; fixed for every reported run), via the OpenAI Agents SDK, temperature 0, fixed prompts. List prices used for cost estimates: $0.75 per million input tokens, $4.50 per million output tokens.
- **Cache-based reproducibility.** Every agent call is cached on disk (`data/llm_cache/`, committed) under a key made of the agent name, model, instructions and prompt. A rerun whose inputs are identical hits the cache, makes no API call, and returns the saved answer; the simulation itself is deterministic given the scenario file and seed. Changing a prompt, a tool, the model or the scenario state changes the key and calls the API. Runs are therefore reproducible, but the cache records one sample per input: run-to-run variance of the model is not measured.
- Logged tokens are *logical* (what the run would cost without caching); `fresh_tokens` is what was actually sent on that run. Costs in the results are list-price estimates.

## 15. Frozen-tag protocol

Nothing that could favour a system was changed after the stage that depends on it was frozen. Git tags mark each freeze:

| Tag | Frozen before | What it fixes |
|---|---|---|
| `calibration-frozen` | any agent run | scenario settings (severity weights, deadlines, fleet) |
| `environment-frozen` | any agent run | final environment; baseline results verified identical |
| `agents-frozen` | test-seed runs | agent prompts and tools (v1) |
| `v2-frozen` | the v2 runs | v2 admission negotiation and prompts |
| `dashboard-v1` / `dashboard-v2` | (dashboard only) | working dashboard before the redesign / the final dashboard |

Results are kept per version in `results/<version>/` and `logs/<version>/`. v1 is write-protected in the runner (it needs `--allow-v1-write`; the only later v1 writes added missing grid cells, see `docs/EXPERIMENT_LOG.md`), every v2 run declares `--version v2`, tables carry a `version` column, and v1 and v2 rows are never pooled.

## 16. Development seeds

Seed 42 was used to develop and check the system: the v2 dev-seed checks ran on **normal 42, bottleneck 42** and surge 42 before v2 was frozen (`docs/V2_DESIGN.md` section 15). Those seeds are included in the reported grids (they are the first seed of each scenario), so the reported samples are not fully held out. No prompt was changed after the v2 dev-seed check.

## 17. Formulaic-report limitation

Incident reports are written by an LLM from a structured template (incident type, number of people, and capability-neutral signs for each victim's condition), generated once and cached (`data/descriptions/`). They are more uniform and easier to parse than real 911 calls, so the Assessment agent's task is easier than in practice, and a real deployment would face noisier, contradictory and incomplete reports. Extraction accuracy against ground truth is reported in `results/v1/assessment_accuracy.json`.

## 18. v2 design and findings

Design (full text in `docs/V2_DESIGN.md`): Dispatch requests a destination hospital for an ambulance's load; Hospital Coordination accepts, rejects or counters (a counter names another hospital for the *whole* load, because one ambulance goes to one hospital); Dispatch may revise; up to 3 rounds; Resource Allocation arbitrates leftovers; a fixed nearest-capable-hospital rule is the fallback. It is enabled only for `--version v2`. v1 code paths, prompts and the baselines are unchanged (a test checks the baselines are identical).

Findings (all numbers in `docs/RESULTS.md`): over 25 negotiation runs, 372 admission requests were made, 364 hospital accepts, 14 rejects, 0 counters, 6 revisions by Dispatch and 1 arbitration; no admission fallbacks. ER beds were never full in greedy or negotiation runs (peak occupancy at most 56% on average), so admission negotiation rarely binds, and the binding constraint is ambulances. No significant difference in critical service rate between v2 and v1 for the same agents. v2 did not reduce infeasible proposals (334 versus 209 in v1); the validator blocked all of them. Subset counters were not implemented (future work), nor was a treatment-slot reviewer.

## 19. Data sharing and cost

The agent runs used OpenAI's complimentary daily token allowance for the model, which is available in exchange for sharing the prompts and responses with the provider. All prompts contain only synthetic scenario text and simulation state, never real or personal data. The experiments used about 9.9 million logical tokens in 106 agent runs ($9.53 at list price, see `docs/RESULTS.md`); the fresh tokens actually sent were 2.66 million (v1) and 1.77 million (v2). No `.env` or API key is committed.

## 20. Display-only marker spreading

On the dashboard map, incident markers that are closer than 1.9 km, or closer than 1.9 km to a hospital icon, are nudged apart (at most 2 km, deterministic) so their glows and labels do not overlap (`src/erc/dashboard/spread.py`). This changes **display positions only**: the true location stays in the data and in every calculation, results and logs are untouched. Units parked or stacked at the same place are likewise drawn with small offsets.

## 21. Limitations

Synthetic grid instead of real roads; simplified deterioration and treatment; no real hospital data or dispatch regulations; small fixed infrastructure; results describe this simulation under these assumptions and are not claimed to generalise to real emergencies. The agents use one model and one run per seed, the report generator is formulaic (section 17), and the seed counts are small (10, 10 and 5 per scenario; 3 for the oracle), so most comparisons are not statistically significant.
