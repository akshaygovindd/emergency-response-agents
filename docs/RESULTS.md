# Results

Final analysis of the saved experiments. Everything here is computed from `results/<version>/runs.jsonl`,
`logs/<version>/<mode>/*.jsonl` and the scenario files in `data/scenarios/` by one script, with no simulation
and no API calls:

```bash
python scripts/analysis.py          # writes results/analysis/*.csv and *.png
```

Tables are CSV files in `results/analysis/` (named `01_...` to `07_...`, each cited below); figures are 16:9 PNGs
in the same folder, drawn with the dashboard design-system colors. **v1** is the frozen pilot (hospital agent
proposes destinations, no admission negotiation); **v2** adds hospital accept / reject / counter on admissions.
The two versions are never pooled. Naive and greedy are identical in v1 and v2 (checked: paired difference 0 on every seed), so
their rows repeat.

**How the per-victim numbers were obtained.** First-contact times per victim are not stored in the logs, so
`scripts/analysis.py` rebuilds them from the same events the engine uses (ambulance arrival on scene, medical team
arrival). The rebuilt critical service rate and mean response time match `results/` for **all 206 runs**
(`00_reconstruction_check.csv`, enforced by `tests/test_analysis.py`).

**Systems:** naive, greedy (rule-based baselines), agents (LLM agents with a fixed priority rule, no negotiation),
negotiation (Resource Allocation agent arbitrates, counter-offers, max 3 rounds, fallback), oracle (negotiation
with ground-truth assessments; v1 only, 3 seeds). **Primary metric:** critical service rate (CSR), the share of
critical victims (severity 4-5) first contacted within their deadline. Seeds: normal 10, surge 10, bottleneck 5.
Intervals are 95% t-intervals across seeds; "paired" means seed by seed on the same scenario.

**Research questions.** RQ1: do agent systems beat strong rule-based allocation? RQ2: does negotiation help? RQ3: how does
performance change as demand rises (normal to surge to bottleneck)? RQ4: what does it cost? Supporting analyses (oracle,
contention, v2 vs v1, failures) follow RQ4.

## Headline

* No agent system is significantly better or worse than greedy in any scenario in either version; every paired
  interval contains zero. Both beat naive by a wide, significant margin.
* Negotiation versus agents without negotiation: no significant difference. Most paired runs are identical (35 of 50
  never diverged); where they did, the effect is mixed.
* Every system's critical service rate falls steeply as demand rises; the agent-minus-greedy gap moves from about 0 (normal) to +3 to +4 points (bottleneck), not significant. Ambulance conflicts per run fall as pressure rises, and ER beds were never full in greedy or negotiation runs.

## RQ1. Do agent systems beat strong rule-based allocation?

CSR, mean over seeds [95% CI] (`01_csr.csv`; figures `fig01_csr_v1.png`, `fig01_csr_v2.png`):

**v1**

| scenario | naive | greedy | agents | negotiation | oracle (3 seeds) |
|:--|:--|:--|:--|:--|:--|
| normal (10) | 35.8% [26.3, 45.2] | 58.5% [38.2, 78.9] | 55.0% [38.6, 71.5] | 57.8% [40.8, 74.8] | 74.2% [12.0, 100] |
| surge (10) | 13.8% [11.7, 15.9] | 25.0% [20.9, 29.1] | 25.2% [21.4, 29.0] | 26.2% [20.7, 31.7] | 19.7% [0, 46.8] |
| bottleneck (5) | 8.5% [5.5, 11.6] | 17.2% [12.8, 21.6] | 21.2% [11.5, 30.9] | 21.2% [11.5, 30.9] | - |

**v2**

| scenario | naive | greedy | agents | negotiation |
|:--|:--|:--|:--|:--|
| normal (10) | 35.8% [26.3, 45.2] | 58.5% [38.2, 78.9] | 59.1% [41.1, 77.1] | 59.1% [41.1, 77.1] |
| surge (10) | 13.8% [11.7, 15.9] | 25.0% [20.9, 29.1] | 25.8% [20.8, 30.8] | 24.7% [19.5, 29.9] |
| bottleneck (5) | 8.5% [5.5, 11.6] | 17.2% [12.8, 21.6] | 20.1% [10.1, 30.0] | 20.1% [10.1, 30.0] |

Paired difference versus greedy, points [95% CI], wins/losses/ties by seed (`01_rq1_paired_vs_greedy.csv`, `fig02_rq1_vs_greedy.png`):

| scenario | system | v1 | v2 |
|:--|:--|:--|:--|
| normal | naive | -22.7 [-36.0, -9.4] 0/8/2 (significant) | same |
| surge | naive | -11.2 [-16.0, -6.5] 0/10/0 (significant) | same |
| bottleneck | naive | -8.7 [-12.6, -4.7] 0/5/0 (significant) | same |
| normal | agents | -3.5 [-21.9, +15.0] 2/3/5 | +0.6 [-19.5, +20.6] 4/3/3 |
| surge | agents | +0.1 [-4.2, +4.5] 3/3/4 | +0.8 [-4.0, +5.5] 4/3/3 |
| bottleneck | agents | +4.0 [-7.0, +15.1] 3/1/1 | +2.9 [-7.2, +13.0] 3/1/1 |
| normal | negotiation | -0.8 [-18.5, +17.0] 3/3/4 | +0.6 [-19.5, +20.6] 4/3/3 |
| surge | negotiation | +1.1 [-3.9, +6.1] 5/2/3 | -0.3 [-5.8, +5.1] 4/4/2 |
| bottleneck | negotiation | +4.0 [-7.0, +15.1] 3/1/1 | +2.9 [-7.2, +13.0] 3/1/1 |

By triage color (share served in time, `01_triage_by_color.csv`, `fig05_triage_v1.png`, `fig05_triage_v2.png`), normal scenario, v1:
Immediate greedy 58.5% / agents 55.0% / negotiation 57.8%; Delayed 73.5% / 52.3% / 56.4%; Minor 80.5% / 88.1% / 91.9%.
v2 normal: Immediate 58.5% / 59.1% / 59.1%; Delayed 73.5% / 50.9% / 48.6%; Minor 80.5% / 87.5% / 90.5%.

**Takeaway.** The agent systems do as well as greedy on critical victims, within noise, and much better than naive.
They do not beat greedy. The visible pattern is a trade between colors: in the normal scenario agents serve more
Minor victims and fewer Delayed ones than greedy (about 49-56% versus 73.5% for Delayed).

**Limitations.** Every interval contains zero, and with 5-10 seeds the intervals are wide (about +/-20 points in normal),
so "comparable" is the strongest honest claim, not "equal". Many comparisons were made with no multiplicity correction.
Seed 42 served as a development seed (PLAN.md). One run per seed, so run-to-run LLM variance is not measured.

## RQ2. Does negotiation help compared with agents that cannot negotiate?

Paired difference, negotiation minus agents (`01_rq2_negotiation_vs_agents.csv`, `fig03_rq2_negotiation_vs_agents.png`):

| scenario | v1 | v2 |
|:--|:--|:--|
| normal | +2.7 [-1.7, +7.1] 2/0/8 | 0.0 [0, 0] 0/0/10 |
| surge | +1.0 [-1.6, +3.6] 2/1/7 | -1.1 [-3.6, +1.4] 0/1/9 |
| bottleneck | 0.0 [0, 0] 0/0/5 | 0.0 [0, 0] 0/0/5 |

### First divergence (`02_divergence.csv`, `02_divergence_summary.csv`, `fig06_divergence.png`)

Agents and negotiation runs share history until their first different accepted decision, so each pair is a natural experiment.

| version | pairs | diverged | never diverged | negotiation helped | hurt | tied |
|:--|--:|--:|--:|--:|--:|--:|
| v1 | 25 | 8 | 17 | 4 | 1 | 3 |
| v2 | 25 | 7 | 18 | 0 | 1 | 6 |
| both | 50 | 15 | 35 | 4 | 2 | 9 |

By scenario: v1 normal 3 diverged (2 helped, 1 tied); v1 surge 5 (2 helped, 1 hurt, 2 tied); v2 normal 5 (all tied);
v2 surge 2 (1 hurt, 1 tied); bottleneck never diverged in either version. Of the 15 divergences, 13 start at a conflict
that negotiation resolved differently from the priority rule, 5 of them with an accepted counter-offer; 2 (both v2) start at an
admission revision. Helped, hurt and tied compare CSR within the pair.

* **Helped, v1 normal seed 42 (CSR 0.64 to 0.82).** At minute 6 Incident 1 and Incident 2 claimed Ambulance 1. The priority rule sent it to Incident 1;
  negotiation counter-offered Ambulance 3 for Incident 1 and let Ambulance 1 serve Incident 2. Two critical victims at Incident 10 were reached in time only in the negotiation run.
* **Hurt, v2 surge seed 44 (CSR 0.296 to 0.185).** At minute 2 the only free ambulance, Ambulance 2, was claimed by Incident 3 (two non-critical victims, far south) and Incident 2 (one severity-3 victim).
  The priority rule gave it to Incident 2; negotiation gave it to Incident 3. Incident 3's victims were reached at minute 19 instead of 98,
  but critical victims V-07-1, V-13-4 and V-17-4 were never reached in the negotiation run (V-07-1 had been reached at minute 41 by Ambulance 2 in the agents run), and one critical victim, V-12-1, was gained.
  The negotiation preferred the incident with more victims although neither was critical.

### Per-conflict outcomes (`03_conflicts.csv`, `03_conflict_summary.csv`, `fig07_conflict_resolutions.png`)

| version | conflicts | counter-offer accepted | negotiated, no counter | fallback |
|:--|--:|--:|--:|--:|
| v1 | 29 (23 ambulance, 6 ER capacity) | 5 | 24 | 0 |
| v2 | 25 (24 ambulance, 1 routing) | 1 | 23 | 1 |

The 7 critical victims in accepted counter-offers (6 in v1, 1 in v2) were all reached in time, but they were also reached in time in the paired agents run:
the counter changed who waited, not whether these victims were served. Conflicts without a counter are mostly contested ambulances with little slack:
critical victims in the contested proposals were reached in time for 5 of 21 (v1) and 2 of 21 (v2), because someone must wait when two incidents want one unit.

**Takeaway.** Negotiation changes decisions rarely (15 of 50 pairs), and when it does the net effect on critical victims is small and goes both ways.
It helped in four pairs in v1 and in none in v2, and hurt in two.

**Limitations.** Each pair is one run, so attribution is a single case, not a distribution. 4 helped versus 2 hurt is far too few for a conclusion.
The "same victims in the agents run" check shows association, not a controlled counterfactual for downstream victims.

## RQ3. How does performance change as demand rises?

Scenarios are ordered by pressure on ambulances: normal, surge, bottleneck (`01_csr.csv`, `01_rq1_paired_vs_greedy.csv`, `04_contention.csv`; figure `fig12_rq3_demand.png`).

CSR by system (mean over seeds), v1 / v2:

| system | normal | surge | bottleneck |
|:--|--:|--:|--:|
| naive | 35.8% / 35.8% | 13.8% / 13.8% | 8.5% / 8.5% |
| greedy | 58.5% / 58.5% | 25.0% / 25.0% | 17.2% / 17.2% |
| agents | 55.0% / 59.1% | 25.2% / 25.8% | 21.2% / 20.1% |
| negotiation | 57.8% / 59.1% | 26.2% / 24.7% | 21.2% / 20.1% |
| oracle (v1, 3 seeds) | 74.2% | 19.7% | - |

Gap to greedy, points [95% CI], v1 / v2 (all intervals contain zero):

| system | normal | surge | bottleneck |
|:--|:--|:--|:--|
| agents | -3.5 [-21.9, +15.0] / +0.6 [-19.5, +20.6] | +0.1 [-4.2, +4.5] / +0.8 [-4.0, +5.5] | +4.0 [-7.0, +15.1] / +2.9 [-7.2, +13.0] |
| negotiation | -0.8 [-18.5, +17.0] / +0.6 [-19.5, +20.6] | +1.1 [-3.9, +6.1] / -0.3 [-5.8, +5.1] | +4.0 [-7.0, +15.1] / +2.9 [-7.2, +13.0] |
| naive | -22.7 / -22.7 | -11.2 / -11.2 | -8.7 / -8.7 |

Link to the contention numbers (`04_contention.csv`):

| | normal | surge | bottleneck |
|:--|--:|--:|--:|
| critical victims per ALS ambulance | 4.2 | 11.45 | 16.4 |
| share of first 75 min with no free ambulance (greedy) | 64% | 85% | 96% |
| ambulance conflicts per run, v1 / v2 | 1.6 / 1.75 | 0.7 / 0.5 | 0.4 / 0.2 |

* **Everyone degrades.** Greedy falls from 58.5% to 25.0% to 17.2%, and every system follows the same shape in both versions. Demand per ALS ambulance rises almost four-fold (4.2 to 16.4)
  while the share of minutes with no free ambulance climbs from 64% to 96%, so most critical victims cannot be reached by their deadline whatever the policy.
* **The agent-minus-greedy gap grows with pressure.** Agents and negotiation are at or slightly below greedy in normal (-3.5 to +0.6), near zero in surge (-0.3 to +1.1) and ahead in bottleneck (+2.9 to +4.0;
  21.2% / 20.1% versus 17.2%). The ordering is the same in both versions, but every interval contains zero and bottleneck has only 5 seeds, so this is a direction, not a finding. The naive gap shrinks (-22.7, -11.2, -8.7) mostly because the baseline floor is lower.
* **Why negotiation cannot be the reason.** As pressure rises the ambulances are busy almost all the time, so two proposals rarely claim the same free ambulance in the same minute: conflicts fall 1.6 to 0.7 to 0.4 (v1) and 1.75 to 0.5 to 0.2 (v2).
  In bottleneck, negotiation and agents without negotiation never diverged (5 of 5 identical in both versions), so the bottleneck gain over greedy, if real, comes from the agents' dispatch decisions rather than from negotiation.
  What causes it was not tested here.
* **Where negotiation had a chance to matter** is normal and surge, where conflicts still occur: 15 of 50 pairs diverged in total, all in those two scenarios (RQ2).

**Takeaway.** Performance of every system drops sharply as demand rises, and the more the ambulances are the bottleneck the less there is to negotiate about, so the contested-resource
conflicts that negotiation is designed for become rarer exactly when pressure is highest. Agents look relatively better than greedy under the heaviest load, but the evidence is weak.

**Limitations.** Three scenarios, not a continuous demand sweep, and they differ in more than load: bottleneck has 2 ambulances, a compressed arrival window (19 minutes) and 5 seeds, and surge and bottleneck are not on one scale
(incidents per ambulance-hour in the arrival window: 2.0, 4.1, 16.0). The widening gap rests on non-significant differences from 5 to 10 seeds, and the oracle point at normal (3 seeds, interval 12% to 100%) is not comparable to the 10-seed means.

## RQ4. What does it cost?

Per run at list price from logged tokens, as if nothing were cached (`07_cost_overall.csv`, `07_cost_benefit.csv`, `fig11_cost_vs_benefit.png`):

| version | system | runs | cost per run | tokens per run | model calls | model time per run |
|:--|:--|--:|--:|--:|--:|--:|
| v1 | agents | 25 | $0.089 | 92,464 | 46.5 | 95 s |
| v1 | negotiation | 25 | $0.089 | 93,032 | 47.9 | 97 s |
| v1 | oracle | 6 | $0.074 | 82,554 | 34.2 | 75 s |
| v2 | agents | 25 | $0.086 | 88,788 | 46.8 | 93 s |
| v2 | negotiation | 25 | $0.099 | 100,216 | 61.9 | 111 s |

All 106 agent runs together: $9.53 and 9.86 million tokens at list price. Naive and greedy make no model calls. Model time is the summed latency of the logged calls.
Scenario means are in the CSV: from $0.042-0.049 per run in bottleneck to $0.113-0.132 in surge.
Critical-service difference versus greedy has an interval containing zero in every row, so there is no measured benefit to divide the cost by (`usd_per_extra_point` is only
filled where the point estimate is positive and should not be read as a result). In v2, negotiation costs 15% more per run than agents without negotiation ($0.099 vs $0.086) for no measurable gain.

**Takeaway.** An agent run costs about nine cents and 1.5-2 minutes of model time, and buys no measurable improvement over a rule that is free and instant.
**Limitations.** Cost is list price from logged tokens, not what was paid: of the 9.86 million tokens, 2.66 million (v1, of 5.13 million) and 1.77 million (v2, of 4.73 million) were fresh API tokens, the rest came from the cache (`fresh_tokens` in `runs.jsonl`). Model time is a sum over calls, not wall-clock.

## Supporting analyses

### Oracle ablation (v1 only, 3 seeds) (`01_oracle_ablation.csv`, `fig04_oracle_ablation.png`)

Oracle minus negotiation: normal -11.4 [-42.8, +20.1] (0/2/1), surge -1.5 [-20.9, +17.9] (1/2/0). Perfect victim assessments did not improve CSR
and the three-seed intervals are far too wide to conclude anything. (The oracle's raw means in the RQ1 table use 3 seeds and are not comparable to 10-seed means.)

### Contention per scenario (`04_contention.csv`, `fig08_contention.png`)

| | normal | surge | bottleneck |
|:--|--:|--:|--:|
| incidents / victims / critical (mean) | 12 / 27.9 / 8.4 | 25 / 55.9 / 22.9 | 10 / 24.4 / 16.4 |
| ambulances (ALS) | 5 (2) | 5 (2) | 2 (1) |
| critical victims per ALS ambulance | 4.2 | 11.45 | 16.4 |
| incidents per ambulance-hour (120 min / arrival window) | 1.2 / 2.0 | 2.5 / 4.1 | 2.5 / 16.0 |
| peak victims waiting at once (greedy) | 12.4 | 36.8 | 21.4 |
| peak critical victims waiting (greedy) | 3.5 | 15.0 | 14.0 |
| share of first 75 min with no free ambulance (greedy) | 64% | 85% | 96% |
| ambulance conflicts per run, v1 / v2 (agent systems) | 1.6 / 1.75 | 0.7 / 0.5 | 0.4 / 0.2 |
| ER-capacity conflicts per run, v1 / v2 | 0.15 / 0 | 0.5 / 0 | 0 / 0 |
| peak ER occupancy, mean per run (greedy) | 47% | 56% | 18% |

Demand rises from normal to surge to bottleneck on every ambulance measure, while ambulance conflicts fall. A conflict needs two proposals for the
same free ambulance in one minute; at high pressure no ambulance is free (64% to 85% to 96% of minutes), so incidents queue instead of colliding.
ER beds rarely bind: no greedy or negotiation run ever had a full ER, mean peaks stay at or below 56%, and ER-full events occur only in surge at 0.05 per run pooled over all systems.
The ER-capacity conflicts in v1 are projected overloads ("H-T ER would hold 7 of 6"), and they do not occur in v2. Scenario inputs come from `data/scenarios` (shared by both versions);
conflicts, waiting and ER peaks come from each version's own results and logs.
**Limitation:** this shows the scenarios stress ambulances, which is the intended design, and that the negotiation has little to negotiate over when conflicts are this scarce (0.2-1.75 per run).

### v2 versus v1 (`05_v1_vs_v2_critical_service.csv`, `05_admission_stats.csv`, `05_admission_methods.csv`, `fig09_v1_vs_v2.png`)

What changed (design in `docs/V2_DESIGN.md`): in v1 the Hospital Coordination agent chose destinations; in v2 Dispatch requests a hospital and the hospital agent accepts, rejects or
counters, with Resource Allocation arbitrating leftovers and a fixed fallback. Admission negotiation in v2 (summed over 25 runs per system):

| system | requests | hospital accepts | rejects | counters | revisions by Dispatch | arbitrated | fallbacks | rule redirects |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| agents | 371 | 361 | 10 | 0 | - | - | 0 | 4 |
| negotiation | 372 | 364 | 14 | 0 | 6 | 1 | 0 | 0 |

The hospital agent never used the counter-proposal path; negotiation is effectively accept or reject (v1 had no admission negotiation, so all its admission counts are zero).

Paired v2 minus v1 CSR, same agents and seeds: agents normal +4.0 [-4.3, +12.4], surge +0.6 [-4.3, +5.6], bottleneck -1.1 [-4.2, +2.0]; negotiation normal +1.3 [-6.6, +9.3],
surge -1.5 [-6.2, +3.3], bottleneck -1.1 [-4.2, +2.0]. None is significant. **Takeaway:** v2 added a second negotiation type without a detectable change in outcomes.

### Failure analysis (`06_failure_runs.csv`, `06_failure_victims.csv`, `fig10_failures.png`)

31 agent-system runs scored below greedy on the same scenario and seed (v1: 16 of 56, v2: 15 of 50; pairs where the system ties or wins are the rest). In those runs greedy reached
94 critical victims in time that the system did not (52 in v1, 42 in v2); the system also reached some greedy missed, listed in the CSV.
Why the 94 were lost: 50 were dispatched later than greedy dispatched them, 26 never got an ambulance, 10 got a different and slower ambulance, 4 got one too late to be reached at all,
and 4 were first contacted by an ambulance where greedy's medical team had arrived earlier. In 84 of the 94 cases no ambulance was free in the system's run at the minute greedy dispatched,
so the loss traces to earlier commitments; in 10 cases an ambulance was free but a slower one was chosen. Nine of the 31 runs begin with greedy sending a medical team that the agent system did not send at that minute
(v1 and v2 bottleneck seed 46, normal seed 51, v1 oracle surge seed 43).

Examples: v2 surge seed 44, negotiation 0.185 versus agents and greedy 0.296 (see RQ2). v1 surge seed 44, negotiation 0.185, agents 0.222, greedy 0.296: at minute 0 the agent systems used Ambulances 1 and 4 for Incident 1
while greedy used Ambulances 4 and 5 plus the medical team; at minute 1 the critical victim V-02-1 (deadline 9) then received Ambulance 3 instead of Ambulance 1, and was reached at minute 13 instead of 3.
Largest gap: normal seed 49 in both versions (0.30 versus 0.80, five critical victims lost).

**Reliability** (`06_invalid_proposals.csv`, `06_reliability_summary.csv`). Invalid proposals, all rejected by the validator before execution (zero actions rejected at execution in any of the 106 agent-system runs; per-system counts in the CSV):

| version | agent that made the proposal | hospital_full | hospital_lacks_capability | routing_conflict | total |
|:--|:--|--:|--:|--:|--:|
| v1 (agents + negotiation + oracle) | hospital_coordination | 122 | 84 | 3 | 209 |
| v2 (agents + negotiation) | dispatch | 147 | 119 | 68 | 334 |

(The "160" in PLAN.md is the v1 normal scenario only: 80 invalid proposals in each of the agents and negotiation runs; the totals above cover all scenarios.)

v2 did not reduce infeasible proposals; they moved from the hospital agent to Dispatch (163 and 171 in agents and negotiation, versus 106 and 101 in v1). The validator caught every one. **Limitation:**
a blocked proposal still costs a model call and may delay a decision; the table shows safety, not efficiency.

## Limitations (all sections)

* Small samples: 10, 10 and 5 seeds per scenario, 3 for the oracle. Nothing involving agents is statistically significant, so the findings are "no detectable difference", not "no difference".
* One run per seed and system; LLM calls are cached, so reruns are identical and run-to-run variance is unknown.
* Divergence verdicts rest on single paired runs; attributions of downstream effects are case studies.
* Scenario reports are LLM-written from a formulaic generator, so assessments are easier and more uniform than real 911 calls.
* Synthetic 20 x 20 km grid, one model (gpt-5.4-mini), fixed fleet and staff; results do not transfer to real dispatch.
* Costs are list-price estimates; v1 and v2 use different protocols, so v1 versus v2 mixes protocol effect with LLM noise.

## File index

`results/analysis/`: `01_csr`, `01_rq1_paired_vs_greedy`, `01_rq2_negotiation_vs_agents`, `01_oracle_ablation`, `01_triage_by_color`, `02_divergence`, `02_divergence_summary`, `03_conflicts`,
`03_conflict_summary`, `04_contention`, `05_admission_stats`, `05_admission_methods`, `05_v1_vs_v2_critical_service`, `06_failure_runs`, `06_failure_victims`, `06_invalid_proposals`, `06_reliability_summary`,
`07_cost_benefit`, `07_cost_overall`, `00_reconstruction_check` (all `.csv`), and `fig01` to `fig12` (`.png`).
