# Final Plan: Emergency Response Multi-Agent System (CSYE7380, due Nov 4, 6pm)

## Goal
A project that covers every line of the brief, proves its claims with honest evidence,
and opens with an unforgettable live dashboard demo.

**Claim we defend:** the multi-agent systems substantially outperform the naive baseline and
perform comparably to a strong greedy allocator; negotiation changes decisions under contention
without degrading performance, and we show exactly where and how through causal analysis.

---

## Final scope

### Build
| # | Item | Why |
|---|---|---|
| 1 | **v2: Hospital accepts / rejects / counters admissions** (Dispatch proposes destination; hospital protects capacity for critical patients; Dispatch revises up to 3 rounds; Resource Allocation arbitrates leftovers; no-negotiation mode uses a fixed rule) | Closes the only agent gap vs the brief; adds a second negotiation type |
| 2 | **Animated replay dashboard** (Streamlit shell + embedded JS player): smooth movement, triage-colored victims incl. Expectant, route lines, conflict callouts, auto-pause at conflicts, KPI cards, hospital bed cards, color-coded agent feed, negotiation strip, timeline with conflict markers | Prof. Das: the final opens with the dashboard |
| 3 | **Story mode (Tour):** bookmarked moments of the best run with one-line captions | Makes the demo impossible to get lost in |
| 4 | **What-if panel:** change ambulances / incidents / seed, run naive + greedy live in seconds (agents optional, with token warning) | "Things change when we change something" |
| 5 | **Compare page:** same run, greedy vs negotiation side by side | Shows the difference visually |
| 6 | **Results page:** RQ1 to RQ4 charts, results by triage color and scenario | Evidence in the dashboard |
| 7 | **Negotiation explorer:** every conflict, proposals, counter-offers, outcome, raw JSON message | Covers "allocation and negotiation history" |

### Analysis
| # | Item | Why |
|---|---|---|
| 8 | **First-divergence analysis:** agents and negotiation share history until their first different decision, so each paired run is a natural experiment; report where negotiation changed a decision and what happened to patients after | Causal evidence beyond averages |
| 9 | **Per-conflict outcomes** (negotiated choice vs what the rule would have chosen) | Shows where negotiation helps |
| 10 | **Results by triage color** and **contention numbers per scenario** + scenario map | Proves scenarios force trade-offs |
| 11 | **Honest failure analysis:** where agents lost to greedy and why | Shows understanding, not just results |
| 12 | **RQ4 cost vs benefit** (list-price cost per run vs outcome change) | Answers the latency/cost question |
| 13 | **v1 vs v2 comparison** (v1 = pilot: 160 infeasible hospital proposals, no admission negotiation) | Shows iteration |

### Quality and delivery
| # | Item |
|---|---|
| 14 | GitHub Actions running tests on every push + badge |
| 15 | Polished README: overview, architecture diagram, results, demo GIF, one-command setup, AI acknowledgment |
| 16 | Updated ASSUMPTIONS.md (model, cache reproducibility, dev seeds, frozen protocol, formulaic-reports limitation, v2 changes) |
| 17 | Dashboard deployed (Streamlit Community Cloud) + one-command local launch |
| 18 | Final slides: architecture with OOP design, agents and messages, data, results per RQ with one-line takeaways, divergence evidence, failure analysis, limitations, future work, AI acknowledgment |
| 19 | Backup demo video (2 to 3 min) + rehearsed script |

### Explicitly out of scope (future work in report)
Staff sharing between hospitals, one agent per hospital, city zones / shifts / disruptions,
human approval step, more seeds.

---

## Schedule (40 hours)

| Session | Hours | Work | Done when |
|---|---|---|---|
| **0** | 0.5 | Check Canvas / email Prof. Das for the **rubric**; map items to this plan | Rubric mapped |
| **1** | 8 | **v2 build:** design, implement, tests, dev-seed check (bottleneck 42, normal 42), regression on baselines, freeze `v2-frozen`, push | Tag pushed; tests green |
| **2** | 1 + background | **Start v2 reruns** (normal, bottleneck, surge; agents + negotiation only, no oracle: v1 already covers the information ablation; ~5M tokens over 2 days, or pay ~$2-4 to finish faster) | Runs progressing |
| **3** | 12 | **Animated player:** export bundle + tests, map + movement, incidents + triage, KPIs + hospitals + feed, conflicts + auto-pause + strip, styling, offline assets | Golden run plays smoothly |
| **4** | 5 | Story mode, what-if panel, compare, results, negotiation explorer pages | All pages work |
| **5** | 5 | Analysis: divergence, per-conflict, triage breakdown, contention + map, failure analysis, RQ1-RQ4, v1 vs v2 | Tables and charts final |
| **6** | 3 | README, ASSUMPTIONS, CI badge, deploy | Live link works |
| **7** | 3 | Slides + AI acknowledgment | Deck final |
| **8** | 2.5 | Demo video + 2 full rehearsals with timing | Video exported |
| | **40** | | |

## Checkpoints
- **End of session 1:** if v2 is not frozen, drop it and finish on v1 (normal + surge v1 complete; v1 bottleneck and oracle runs are being completed as v1).
- **Mid session 3:** if the JS player is not playing a run smoothly, fall back to the Streamlit + Plotly redesign (milestone 2 prompt).
- **24 hours before deadline:** feature freeze. Only fixes, slides, video.

## Rules
- Never change frozen code without a new tag; never mix v1 and v2 results.
- Experiments only with explicit permission (token budget); check OpenAI Usage before each batch.
- `pytest -q` green before every commit; commit and push after each completed step.
- Every claim on a slide must trace to a number in `results/`.
