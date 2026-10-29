# v2 design: hospital admission negotiation

Status: **approved** (with the conditions in section 13). No code, logs, results, or API calls yet.

## 0. What v1 does today (as read from the code)

- The **Hospital Coordination Agent proposes** the destination itself (`submit_admission`). Dispatch
  "never chooses hospitals". There is no review, no reject, no counter between the two.
- Admission proposals can be made as soon as an ambulance is *assigned* (victims are in
  `state.reservations`), not only when it has loaded patients. `hospital_situation` lists every
  reserved victim without an admission.
- A proposal that is the only claim on a hospital goes straight to validation. Only *conflicts*
  (capacity, routing, shared resource) reach Resource Allocation (RA).
- The engine sends an ambulance to a hospital only when **every** victim on it has the same
  admission (`Engine._destination`); otherwise it waits on scene.
- Agent calls are cached on (agent name, model, instructions, prompt).

## 1. Target behaviour

Admissions become a negotiation between Dispatch (requests) and Hospital Coordination (reviews).

```
Dispatch --PROPOSAL (admission request)--> Hospital Coordination
Hospital Coordination --ACCEPT | REJECT | COUNTER_PROPOSAL--> Dispatch
(up to 3 rounds) -> Resource Allocation arbitrates leftovers -> fixed fallback rule
```

Python owns reality at every step: every request, counter, revision, and final choice is checked by
`validate()` before it can be sent, and the engine validates again at execution.

## 2. Decisions that need your approval (read these first)

1. **Subset counters are dropped.** The brief asks for "a subset of the victims". Physically that
   cannot work: one ambulance goes to one hospital, the validator rejects a co-passenger going
   elsewhere (`ROUTING_CONFLICT`), and `Engine._destination` returns `None` unless all victims share
   a hospital, so a split would leave the ambulance parked on scene forever. Ambulance capacity is
   2, and splitting needs a second vehicle, which would mean changing the simulation. **Proposal:**
   COUNTER names *another hospital for the whole load*. A subset is mentioned only as future work.
2. **Request timing = v1 timing.** A request is made when an ambulance has reserved victims and no
   destination, same as v1 (not only once loaded). Waiting for "patients on board" would cost a
   minute per trip (the engine moves ambulances before the policy runs) and would make v2 look worse
   for reasons unrelated to negotiation. It also lets "promised" beds appear early.
3. **v1 stays reproducible.** v2 is selected by a code path flag (`admission_protocol="v2"`, set by
   `run_one` when `version == "v2"`). The v1 prompts, tools, and code path are untouched, so v1
   cached reruns stay free and identical. Because the brief says not to change prompts for the frozen
   experiment, v2 adds **new** agents/prompts rather than editing `DISPATCH_INSTRUCTIONS`. Dispatch's
   ambulance-assignment agent is therefore left unchanged and keeps hitting its cache wherever the
   state matches v1.
4. **No simulated time is spent negotiating.** All rounds happen inside one policy call at one
   simulation minute. Negotiation costs tokens, not minutes. (Same as v1's conflict negotiation.)

## 3. Exact flow per decision round (`_decide`)

Unchanged steps are marked `=`.

1. `=` Assess new incidents (Assessment Agent, or ground truth in oracle mode).
2. `=` **Dispatch ambulance/team proposals** (`DispatchAgent`, same prompt, same tools). Run only if
   `needs_dispatch`.
3. **NEW: Dispatch destination requests.** If any reserved victims lack a destination
   (`needs_hospital` condition, unchanged), run the new `DispatchDestinationAgent`. It gets one tool,
   `submit_admission_request(ambulance_id, hospital_id, victim_ids, reason)`, which checks the
   validator immediately and returns feedback (same pattern as v1 tools). Accepted requests are stored
   as `AdmissionRequest`s (not yet in the proposal pool). Each request is logged as
   PROPOSAL `dispatch -> hospital_coordination`, `negotiation_id = ADM-<round>-<n>`, `round = 1`.
4. **NEW: Hospital review** (the "admission negotiation", per request, up to 3 rounds):
   - *agents mode:* fixed rule (section 5), one pass, no counters, no rounds.
   - *negotiation:* the **HospitalReviewer** (LLM, one call for all pending requests) returns
     one response per request: ACCEPT, REJECT (+reason), or COUNTER (+ another hospital id for the
     whole load).
   - Python applies responses **in order against a running ledger** of promised beds, so two
     ACCEPTs can never overfill one ER. An ACCEPT that no longer fits becomes a REJECT with reason
     `ledger_full`. Every COUNTER hospital is validated (capability, space, routing) before it is
     forwarded; an invalid COUNTER is treated as a REJECT.
   - Messages: `hospital_coordination -> dispatch`, type ACCEPT / REJECT / COUNTER_PROPOSAL,
     same `negotiation_id`, same `round`, `in_reply_to` the request message.
5. **NEW: Dispatch revision** (rounds 2 and 3, only for REJECTED/COUNTERed, unresolved requests):
   one batched `DispatchRevisionAgent` call (structured output). For each open request it chooses
   `accept_counter`, `request_other` (hospital id; becomes a new PROPOSAL, `round = n`), or
   `escalate`. Accepting a counter logs ACCEPT `dispatch -> hospital_coordination`. The Hospital
   reviewer then answers the new requests (back to step 4 with `round = n`).
6. **NEW: RA arbitration** (negotiation only). A request still unresolved after round 3 is
   escalated (ESCALATE `dispatch -> resource_allocation`). One RA call per round (batched) sees the
   request history and hospital states and picks one feasible hospital or `none`. Result logged as
   ACCEPT/REJECT `resource_allocation -> dispatch`, `round = 3`.
7. **NEW: Fallback rule.** Anything still unresolved (or invalid, or an LLM/parse failure at any
   step) gets the **fixed rule**: nearest capable hospital with space. Logged as an
   `admission_fallback` event. If no capable hospital has space, the request stays pending (the
   ambulance waits, exactly as a v1 `HOSPITAL_FULL` rejection behaves).
8. Each resolved request becomes an `ADMIT_PATIENT` **proposal** (proposer = `hospital_coordination`,
   priority from assessed urgency, as v1) and is appended to `ctx.proposals`.
9. `=` **Ambulance-conflict negotiation stays as is.** `detect_conflicts` runs on the pool; RESOURCE
   conflicts (ambulance/team/victim) go through the existing 3-round RA negotiation. CAPACITY and
   ROUTING conflicts should now be rare because the ledger prevents them, but the code path stays as
   a safety net.
10. `=` COMMIT messages, `Decision`s to the engine, engine validates again.

**No-stranding guarantee.** A REJECT can never be final by itself: it only triggers revision, then
RA, then the fallback rule. The only way a patient ends up without a destination is that no capable
hospital has space, the same as v1.

## 4. Who gets which tools

| Agent | Tools / output | Status |
|---|---|---|
| Assessment | structured report | unchanged |
| Dispatch (ambulances/teams) | `estimate_travel_minutes`, `submit_ambulance_assignment`, `submit_team_assignment` | **unchanged** (same prompt, cache reused) |
| **DispatchDestinationAgent** (new, same Dispatch role) | `estimate_travel_minutes`, `hospital_status`, `submit_admission_request` | new |
| **HospitalReviewer** (new role of Hospital Coordination) | no tools; structured output `list[Review]` | new |
| **DispatchRevisionAgent** (new) | no tools; structured output | new |
| Resource Allocation | existing conflict agents + new `AdmissionArbiter` (structured) | existing + new |
| v1 `HospitalCoordinationAgent` | `submit_admission`, `submit_diversion` | unused in the v2 path, kept for v1 |

Why a reviewer without tools: it needs a fixed view for caching and for a clean accept/reject/counter
schema; counters are validated in Python rather than via tool feedback.

## 5. `agents` mode (no negotiation) for a fair comparison

Dispatch still proposes destinations (same `DispatchDestinationAgent`, so the requests are identical
in kind). Hospital review is a **fixed rule, no LLM, no counters, no rounds**:

```
accept request if the hospital can treat every victim (capability) AND has room (ER occupied
  + promised + load <= capacity)
else redirect to the nearest capable hospital with room (ties: lower id)
else leave pending
```

Logged as ACCEPT, or REJECT followed by an `admission_redirect` (reason `rule: hospital full /
incapable`). Redirects are not counters (`countered = 0`). The only difference between `agents` and
`negotiation` is who reviews and whether rounds happen.

## 6. Prompt changes (summaries; full text in `prompts.py` / `negotiation.py`)

- **DispatchDestinationAgent:** "Propose one hospital for each ambulance with victims and no
  destination. Choose by travel time, matching specialty for urgency 4-5, and avoid hospitals near
  capacity. The Hospital Coordination Agent will review and may counter."
- **HospitalReviewer:** "You protect hospital capacity for critical patients without leaving anyone
  stranded. For each request answer ACCEPT, REJECT (give a reason), or COUNTER (another capable
  hospital with room for the whole load). Reject to keep the last ER bed(s) only if assessed critical
  victims are waiting who can reach this hospital sooner than any other. Never reject when no other
  capable hospital has room." Input: request, per hospital ER occupancy, promised (en-route) patients,
  free beds, free treatment slots by care type, assessed critical victims still waiting with
  estimated minutes to each hospital. **Never** deadlines, ground truth, or future incidents.
- **DispatchRevisionAgent:** "Your request was rejected or countered. Accept the counter if it still
  gets these victims timely care, or request another hospital, or escalate."
- **AdmissionArbiter (RA):** "Pick one feasible hospital for each stalled request to maximise critical
  victims reached in time, or none."

## 7. Changes per file

| File | Change |
|---|---|
| `agents/context.py` | add `AdmissionRequest` model (request id, ambulance, hospital, victims, incident, round, status, history); `AgentContext.admissions: list[AdmissionRequest]`; included in `snapshot_since`/`restore` so cached reruns replay it. |
| `agents/tools.py` | add `submit_admission_request` (+ plain function `propose_admission_request`, testable without an LLM); add `hospital_review_view(ctx, requests, ledger)` (occupancy, promised, slots, waiting assessed critical victims). v1 tools unchanged. |
| `agents/prompts.py` | add `DISPATCH_DESTINATION_INSTRUCTIONS`, `destination_prompt(ctx)`. |
| `agents/agents.py` | add `DISPATCH_DESTINATION_AGENT`, `run_dispatch_destination(ctx)`; v1 agents unchanged. |
| `agents/admission.py` (**new**) | the admission protocol: `PromisedLedger`, `fixed_review(...)` (agents-mode rule), `AdmissionNegotiator` (rounds, revisions, arbitration, fallback). Keeps `negotiation.py` focused on conflicts. |
| `agents/negotiation.py` | add reviewer / revision / arbiter agents + schemas (`Review`, `Revision`, `Arbitration`) and `ask_*` helpers (monkeypatch points for tests). Conflict code untouched. |
| `agents/system.py` | `AgentSystem.__init__(..., admission_protocol="v1")`; in `_decide`, step 3-8 run when `"v2"`, replacing the `run_hospital` call. Message/log helpers reused. |
| `eval/experiment.py` | `run_one` passes `admission_protocol="v2"` for `version == "v2"`; naive/greedy are not touched, so v2 baselines are identical to v1 baselines. |
| `eval/metrics.py` | new fields (section 8), all with defaults so v1 rows still load. |
| `dashboard/feed.py` | formatters for `admission_request`, `admission_response`, `admission_redirect`, `admission_fallback` (and ESCALATE rendering). |
| **Not touched** | `sim/*`, `validator.py`, `models/state.py`, scenario data, `assessment.py`, `config.py` (model stays `gpt-5.4-mini`), baselines, logs/, results/. |

## 8. Logging and metrics

New log events (all through `AgentSystem._record`):
`admission_request`, `admission_response` (decision, reason, hospital), `admission_redirect`,
`admission_arbitrated`, `admission_fallback`. Messages use the existing `agent_message` format.

**Promised beds** are derived, no simulation change: promised = admissions accepted (`action_accepted`
ADMIT) and not yet `handover_complete`. The dashboard computes it from existing events;
`incoming_count()` already exists for the agents' own view. `replay_view` in `state.py` is not edited.

New `RunMetrics` fields (default 0):
`admission_requests`, `admissions_accepted`, `admissions_rejected`, `admissions_countered`,
`admission_counters_accepted`, `admission_rounds_mean` (and `admission_rounds_max`),
`admission_fallbacks`, plus `admission_rule_redirects` (agents-mode redirects).
`counters_accepted` keeps its v1 meaning (conflict counters) to avoid mixing the two.

## 9. Expected token impact (estimates, to be checked on the dev seeds)

v1 reference (from `results/v1`): normal about 87k tokens per agent run, surge about 119k, bottleneck
about 55k; negotiation adds only about 1k over agents.

- **agents mode:** replaces one tool-using Hospital call per round with one tool-using
  DispatchDestination call of similar size. Expect roughly **+0-10%**.
- **negotiation:** adds one HospitalReviewer call per round that has requests (about 1-2k
  tokens each, most rounds), plus revision/arbitration calls only on REJECT/COUNTER. Expect roughly
  **+25-45%** per run (normal about 110-125k, surge about 150-170k, bottleneck about 70-80k).
- Cache reuse: assessment and ambulance-proposal calls match v1 cache entries until a run's state
  diverges from v1's, so some fresh-token savings are possible but not counted on.
- Full v2 grid (about 3 scenarios x seeds, 2 agent modes, no oracle): on the order of **6-8M
  tokens**, more than the ~5M in PLAN.md. Re-estimate after the dev seeds; the checkpoint to drop
  scope stays as in PLAN.md.

## 10. Test plan (no API calls; fake LLM answers as in `tests/test_negotiation.py`)

New `tests/test_admission.py` using `monkeypatch` on the `ask_*` helpers and `LLMResult`:

1. Request validity: invalid hospital (lacks capability / full) is refused by `propose_admission_request`.
2. Hospital ACCEPT: request becomes an `ADMIT_PATIENT` proposal; messages PROPOSAL + ACCEPT, round 1.
3. REJECT then Dispatch requests another hospital, accepted in round 2.
4. COUNTER with valid hospital: Dispatch accepts, counter is committed; metrics count it.
5. COUNTER to an invalid hospital becomes a REJECT (validator guard).
6. Three rounds exhausted: RA arbitration decides; invalid arbitration falls to fixed rule.
7. Unparseable LLM output at each step falls back to the fixed rule (never crashes, never strands).
8. Ledger: two requests for one remaining bed, the second is rejected/redirected, never over-admits.
9. `agents` mode: no reviewer/revision/RA calls (monkeypatch raises if called); rule redirect works;
   no counters.
10. Hospital view contains no deadlines or ground-truth fields (assert on JSON keys).
11. Ambulance-conflict negotiation unchanged (existing tests pass untouched).
12. Metrics from a synthetic log; v1 rows without the new fields still load.
13. Feed formatters for the new events.
14. Regression: naive and greedy v2 results equal v1 results for the same seeds (compare metric
    rows computed offline, no log or result files written).
15. Existing 128 tests stay green.

## 11. Risks

- **Over-rejection hurts patients.** A reviewer that hoards beds delays service. Mitigations: the
  prompt forbids rejecting when no other capable hospital has room, rounds are free in simulated
  time, and fallback guarantees a destination whenever one exists. Residual risk is a worse choice,
  not a stranded patient. Measured on the dev seeds before any full run.
- **Hospital sees only assessments.** If the Assessment Agent under-rates a victim, the reviewer
  protects the wrong beds. This is a real limitation; the v1 oracle ablation measures its size.
- **Token cost** grows (section 9); the daily allowance (~2.5M) means multi-day runs.
- **Cache keys:** new agents mean no cache reuse for them; reruns are free only after the first run.
- **v1 comparability:** v1 has no admission negotiation; v1 vs v2 differences mix "Dispatch proposes
  destinations" with "hospital reviews". The `agents` v2 mode isolates the review effect.
- **Subset counters** are dropped (section 2.1); the brief's wording may be read strictly.
- **Engine quirk:** an admission to a hospital that becomes full before handover is still honored
  (validated at admission time). Unchanged simulation behavior, not fixed in v2.
- **Timing of requests** (section 2.2) is the main design choice that could shift outcomes vs the
  brief's literal reading.

## 12. Phase 2 plan, once approved

Implement per section 7, tests per section 10, `pytest -q` green, a free offline check that v2
baselines equal v1 baselines, commit and push, then **ask before** the dev-seed check (v2 negotiation
on bottleneck 42 and normal 42), which uses OpenAI tokens.

## 13. Approval conditions (recorded)

1. **Four agents only.** Every logged message and `llm_call` uses the existing agent names. The new
   internal helpers are implementation details: destination proposals and revisions are sent as
   `dispatch`, hospital reviews as `hospital_coordination`, arbitration as `resource_allocation`.
2. **No oracle in v2.** The v2 grid is agents and negotiation on normal, surge, and bottleneck. The
   information ablation is covered by v1. The oracle path stays in the code unchanged for v1.
3. **Short prompts.** New prompts stay brief. Measured fresh tokens per run on the dev seeds are
   reported before any full rerun.

## 14. Implementation notes (deviations from sections 7 and 8)

- The protocol, its schemas and its short prompts live in `agents/admission.py` (not `negotiation.py`),
  which avoids a circular import; `negotiation.py` is unchanged.
- A Dispatch request is a normal `Proposal` (ADMIT, proposer `dispatch`) produced by the new
  `submit_admission_request` tool. `AgentSystem` lifts it out of the pool, runs the protocol, and puts
  back the reviewed result under the same proposal ID. No new context model and no `llm_cache` change.
- Request/response events are the existing `agent_message` records (negotiation ids `ADM-<round>-<n>`);
  extra events are `admission_resolved`, `admission_redirect`, and `admission_fallback`.
  Conflict metrics (`negotiations`, `counter_proposals`, ...) ignore `ADM-` messages.
- Fallback-rule choices are sent as `resource_allocation` ACCEPT messages, so hospital accept counts
  only reflect real hospital reviews (or the agents-mode rule).

## 15. Dev-seed findings (normal 42, bottleneck 42, surge 42; agents and negotiation, v2)

All numbers trace to `results/v2/runs.jsonl` and `logs/v2/`. One seed per scenario: these are
observations, not statistics.

| Scenario | Critical service rate, v1 agents / negotiation | v2 agents / negotiation | Invalid proposals v2 | Fresh tokens v2 |
|---|---|---|---|---|
| normal 42 | 0.64 / 0.82 | 0.82 / 0.82 | 0 / 0 | 47.8k / 39.7k |
| bottleneck 42 | 0.18 / 0.18 | 0.18 / 0.18 | 0 / 0 | 25.4k / 7.5k |
| surge 42 | 0.21 / 0.25 | 0.32 / 0.32 | 6 / 6 | 101k / 16k |

Fresh tokens depend on cache order (negotiation ran after agents and reused its Dispatch calls).
Logical tokens (cost without caching) are within about -17% to +2% of v1, so the estimate of +25-45%
in section 9 was too high: the reviewer adds only about 7-9k tokens per run and the destination agent
replaces the old Hospital agent at a similar cost.

1. **Routing improvement from Dispatch choosing destinations.** The gains over v1 come from shorter
   trips, not from hospital review. Dispatch weighs travel time more than the v1 Hospital agent did
   (for example normal 42, t=37: a 3-minute trip to H-B instead of 13 minutes to H-G), so ambulances
   are free earlier and reach later critical incidents sooner. On normal 42 this is the whole
   0.64 to 0.82 change (two critical victims of incident INC-10 reached in 7 minutes instead of 32).
   On surge 42, ambulances were assigned 7-10 minutes earlier for INC-10 and INC-15.
   On bottleneck 42 the rate is unchanged but unserved critical victims rose from 2 to 5, a cascade of
   Dispatch's different incident ordering once trips changed.
2. **Admission negotiation rarely binds.** ER beds were never scarce: peak occupancy on surge 42 was
   H-T 5/6, H-B 3/5, H-G unused, and 0 ER-full events in every run. The binding constraint is
   ambulances (at minute 60 of surge 42: 24 victims waiting, 10 critical, all 5 ambulances busy). The
   reviewer accepted every request on its own judgement across normal, bottleneck, and surge, which is
   the correct call when beds are free. Agents and negotiation produce identical outcomes on these seeds
   and there were 0 conflicts in v2 surge 42.
3. **The one reject, revise, accept chain** (surge 42, `ADM-t006-02`, same chain in both modes):
   - t6 Dispatch requests H-T for V-02-1, V-02-2 (round 1).
   - t6 Hospital Coordination REJECTS: "H-T has no room left". This reject came from the Python
     bed ledger (an earlier request in the same review took H-T's last bed), not from the LLM.
   - t6 Dispatch revises and requests H-B (round 2).
   - t6 Hospital Coordination ACCEPTS H-B. Resolved as `revised`, 2 rounds.
   In agents mode the fixed rule redirected to H-B directly. No counter, arbitration, or fallback
   occurred on real model output (they are covered by offline tests with fake answers).
4. **Invalid proposals (6 on surge 42)** all came from Dispatch's `submit_admission_request`: five
   `hospital_full` and one `hospital_lacks_capability`, refused at once by the tool and retried within the
   run. "Full" counts patients promised but still on the road, so early requests (made at ambulance
   assignment) make hospitals look full long before they are. v1 had the same effect.
5. **Not stranded.** No patient was left without a destination during any run; the only unadmitted
   victim (V-23-4) was assigned at minute 119 of 120.
6. **Future work: treatment-slot reviewer.** The real shortage was H-T trauma treatment slots (all in
   use 45 of 121 minutes on surge 42; 3 critical victims never started treatment). The reviewer sees
   free slots but not how many patients are queued or promised for the same care. Recorded, not applied:
   - *View:* per hospital and care type, `free_slots`, `promised` (en route, needing that care), `queued`
     (in the ER waiting for it), from assessments and state only.
   - *Prompt:* compare `free_slots` with `promised` and `queued`; accept if every victim has a slot;
     otherwise counter with a capable hospital that has a free slot and is at most 8 extra minutes away
     for urgency 4-5 (15 for lower urgency); if none exists, accept (never strand).
   - *Caveat:* the primary metric measures first ambulance contact, so treatment queues do not affect it
     and longer trips could lower it. Evaluate such a change on `treatment_started_rate` and treatment
     wait, not on the critical service rate.
7. **v2 `agents` is a different baseline from v1 `agents`.** In v2 Dispatch chooses the destination
   and hospital review is a fixed rule; in v1 the Hospital agent chose it. Compare v1 and v2 rows only
   with that in mind (and never in one table without the `version` column). Use v2 `agents` as the
   no-negotiation comparison for v2 `negotiation`.

Decision: v2 is frozen as is (no prompt or code changes), tag `v2-frozen`. Admission negotiation is
reported honestly as rarely binding in these scenarios.
