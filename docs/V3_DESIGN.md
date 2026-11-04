# v3 design: hospital staff-sharing negotiation

Status: **implemented and run (tag `v3-frozen`); results are in the v3 section of `docs/RESULTS.md`** (no measurable effect of staff sharing). Built on branch `v3-staff-sharing`, merged into `master`. `results/v1`, `results/v2`, `logs/v1`, `logs/v2` and the
`final-submission` tag are not touched.

## 0. What the code does today, and three findings that shape the design

Read from `engine.py`, `validator.py`, `entities.py`, `agents/admission.py`, `agents/system.py`, `eval/metrics.py`
and the v2 logs.

1. **Staff is never the binding constraint; treatment slots are.** A treatment starts only if the hospital has a
   free slot of that care type, a free bed, a qualified doctor (skill >= 2) and a qualified nurse (skill >= 1).
   Per hospital the doctors can carry 6 concurrent patients (2 x `max_patients` 3) and the nurses 8, while
   the slots total 4 (H-T), 4 (H-B), 5 (H-G). So `_start_treatments` is always stopped by slots first. Lending a
   doctor to a hospital that is already slot-limited changes nothing in the current physics.
   **Measured in the v2 `agents` logs** (read-only, a minute counts when patients are queued for a care type and every
   slot of that type is busy): surge seeds 42-51 have 26-179 such hospital-minutes per run, 3-132 of them with a critical
   patient in the queue; in 26-143 of those minutes per run (surge 42: 143 of 179) another hospital had an idle qualified
   doctor and nurse. Waits are mostly short (critical mean 0-7 min among those who started), but 0-3 critical
   patients per surge run are admitted and never start treatment. Normal and bottleneck show the same pattern
   at lower volume. So the situation in the brief exists in our data; the effect size is an open question.
   Under the final transfer rule (section 1) the lender must also have an idle slot of that care type: 26-129 of
   those hospital-minutes per surge run and 6-81 per bottleneck run still have such a lender.
2. **Messages cannot be sent to oneself.** `AgentMessage` rejects `sender == recipient`, and v2 was approved with
   "four agents only". Hospital-to-hospital negotiation is therefore the one Hospital Coordination agent playing two
   sides. v2 already does the same (Dispatch requests, Hospital Coordination reviews, both as the existing
   names). v3 needs a way to label the sides (section 3).
3. **Cache keys include a hash of the full state** (`state_fingerprint`, a SHA-256 of `state.model_dump_json()`).
   Any new field on `SimulationState`, `Hospital` or `StaffMember` that appears in that dump would change every v1/v2
   cache key and make cached reruns cost tokens. v3 therefore adds nothing to those dumps unless a loan exists
   (section 5).

## 1. Decisions (approved, with the changes marked)

1. **A loan is a transfer, not new capacity (changed).** While a team is on loan the **lender loses one treatment slot of
   that care type per team and the borrower gains one**, capped by the borrower's physical beds (its total treatment
   slots may never exceed `beds`). A loan is allowed only if the lender has that slot **idle at request time** (and an
   idle qualified doctor and nurse). The lender's slot comes back when the team is back. This is the v3 modelling
   assumption (to be listed in `ASSUMPTIONS.md`); it exists only in v3 runs. It gives the lender a real reason to reject:
   it protects capacity for its own incoming critical patients. Because slots, not staff, bind (finding 1), the staff
   travel and the slot transfer together are what a loan means.
2. **Loan unit = one care team (doctor + nurse, same care type), 1 or 2 teams per request.** Approved.
3. **One Hospital Coordination instance per hospital (changed).** Same agent definition and prompt for all three; each
   instance sees only its own hospital's state and interests. Message sender/recipient ids look like
   `hospital_coordination:H-T`. Still four agent types. The self-message rule is relaxed only for two **distinct instances**.
4. **N = 10 minutes** for the primary metric. Approved.
5. **`v2` joins the protected versions** (`PROTECTED_VERSIONS = ("v1", "v2")`). Approved. Tests that wrote v2 into temporary directories use v3 instead.
6. **Baselines in v3**: naive and greedy run in v3 at zero tokens (no loans, so equal to v2). Approved.
7. **Seed 42 is the dev seed.** Approved.
8. **Scope tonight: surge (10 seeds) and bottleneck (5 seeds). Normal is skipped.**

## 2. Loan physics (Python owns reality)

A **loan** `L-<n>` (lender, borrower, care type `c`, `teams` 1-2, `duration_min`, chosen staff IDs, phase, timestamps) is owned by the engine
(visible to agents read-only in `state.staff_loans`). Agents only propose.

Phases, per minute in the engine (`_advance_loans`, after `_finish_treatments`, before `_start_treatments`; only when `staff_loans=True`):

| phase | what happens |
|---|---|
| `transfer_out` | at execution the lender's `treatment_slots[c]` drops by `teams`, the staff become `on_shift = False`, and travel `travel_time_min(seed, lender, borrower, t)` (same traffic model, ambulance speed). |
| `active` | on arrival: staff `hospital_id = borrower`, `on_shift = True`, borrower `treatment_slots[c] += teams`. Lasts `duration_min` from arrival. Ordinary `_free_staff` selection uses them. |
| `recalled` | at expiry the loaned staff go `on_shift = False` (no new patients) and the borrower's extra slots are withdrawn as soon as they are free, so no occupied slot is ever removed and no new treatment starts in them. Patients already in treatment finish. |
| `transfer_back` | once the extra slots are withdrawn and the staff are idle they leave and travel back. |
| `returned` | on arrival the lender's `treatment_slots[c] += teams`, staff `on_shift = True`, `hospital_id = lender`. Automatic. |

Hard rules (validator `ActionType.LOAN_STAFF`, `_check_loan`; every rule has a reason code; the engine re-validates at execution):
* lender and borrower exist and differ; `1 <= teams <= 2`; `20 <= duration_min <= 60`;
* the borrower can already treat `c`, has a patient queued for `c` that cannot start now (no free slot or no free qualified staff), and its slots after all
  loans in flight stay <= `beds` (**not needed** / **beds cap** reason codes);
* the lender has `free_slots(c) >= teams` (**idle slot**, after teams already promised this round) and `teams` idle teams: a doctor with skill >= INTERMEDIATE in `c` and a nurse
  with skill >= BASIC in `c`, both `on_shift`, `current_patients == 0`, at the lender and not themselves on loan;
* after lending, the lender keeps >= 1 slot of `c` **or** has no patient queued or en route for `c`; and its remaining free workload headroom (sum of
  `max_patients - current_patients` of the remaining on-shift doctors, and of nurses) still covers the patients it already holds (queued plus en route);
* staff are chosen by Python at execution (lowest qualifying `staff_id`), never by an agent.

New `RejectionReason` values: `loan_not_needed`, `lender_understaffed`, `lender_no_idle_slot`, `borrower_beds_full`; `staff_unavailable` is reused. ER capacity, ambulances, travel
and deterioration are untouched. The hospital views of the unchanged Dispatch / Hospital prompts already show `free_treatment_slots`, so slots that moved change
destination choices, an indirect effect that is reported.

## 3. Protocol (instances, messages, rounds, arbitration, fallback)

**Instances.** Hospital Coordination runs as `hospital_coordination:H-T`, `:H-B`, `:H-G`. Same `Agent` definition and instruction text; the prompt carries a
`role` (`borrower` or `lender`, `revise` for later rounds) and **only that hospital's own state**: its free slots by care type, its queued and en-route patients with
assessed urgency, its idle teams, loans in flight. A borrower instance also sees, for each lender candidate, only the id and travel minutes. The candidate list is the
set of lenders that pass the validator's hard rules (the same feedback the v1/v2 tools gave), not their loads or patients. A lender instance sees the request
(borrower, care type, teams, duration, the urgencies of the patients it serves) but not the borrower's state. Never deadlines, hidden condition scores or future incidents.

**Trigger (Python).** Evaluated in `Engine._decision_signature` (a new trigger wakes the policy even with no ambulance work; with `staff_loans` off the signature is unchanged) and by the
agent system. For borrower `b` and care type `c`: `queued(b,c) >= 1`, no free slot (or no free qualified staff) for `c`, the part of the queue not covered by teams in flight, and at least
one feasible lender. Logged as `loan_trigger`. If nothing triggers, no model call is made.

**Messages** (`AgentMessage`, `negotiation_id = LN-<round_id>-<n>`). New optional fields `sender_instance` / `recipient_instance` (hospital id) and `sender_id` / `recipient_id` strings such as
`hospital_coordination:H-T`; all omitted from dumps when absent, so old logs and old message types are unchanged. A `loan` object on `ProposedAction` carries the terms.

| step | from -> to | type | content |
|---|---|---|---|
| 1 | borrower instance -> lender instance | `request` (= LOAN_REQUEST) | lender, care type, teams, duration, `serves` (queued victim ids), `incident_id` of the most urgent one |
| 2 | lender -> borrower | `accept` / `reject` (+ reason) / `counter_proposal` | counter = fewer teams and/or shorter duration |
| 3 | borrower -> lender | `accept` (counter) or a new `request` (another lender or amended terms, next round) or `escalate` -> `resource_allocation` | |
| 4 | `resource_allocation` -> borrower | `accept` / `reject` | arbitration result |
| 5 | `resource_allocation` -> borrower | `commit` | final loan, sent to the engine as a `Decision` |

* **Rounds**: up to 3, inside one policy call at one simulation minute; a loan costs tokens and the staff's travel time, nothing else.
* **Requests**: one structured-output call per borrower instance with triggers (no tools); Python validates every field and drops infeasible asks (logged `proposal_invalid`).
  If the call fails or yields no valid ask for a trigger, the fixed rule asks the nearest feasible lender for 1 team, 30 minutes (logged `loan_fallback`).
* **Contention**: when requests for the same lender and care type exceed what that lender has idle (a Python ledger counts teams promised this round, so one slot can never be lent twice),
  Resource Allocation decides who gets it (LLM in negotiation, the priority rule in agents); the others are rejected and may ask another lender next round.
* **Fallback**: unresolved after round 3, unparseable or invalid -> the fixed rule. If no feasible lender exists nothing is lent and the queue waits, as today.
* **Fixed rule** (agents mode and every fallback): the lender accepts the full request if the validator passes **and** it has no assessed-critical (urgency >= 4) patient queued or en route; otherwise it rejects.
  No counters. Contention priority: higher maximum assessed urgency among `serves`, then more critical queued, then lower borrower id, then request id.

## 4. `agents` mode versus `negotiation` mode (clean comparison, as in v2)

| | agents | negotiation |
|---|---|---|
| trigger, request generation by the borrower instances, validator, physics | identical | identical |
| lender decision | fixed rule, one pass; on a reject the rule asks the next nearest feasible lender (like the v2 rule redirect) | lender instance (LLM): accept / reject / counter |
| rounds, counters, borrower revision | none | up to 3 (borrower instance revises) |
| contention | fixed priority rule | Resource Allocation arbitration (LLM), then fixed rule |

Ambulance-conflict negotiation and v2 admission negotiation are unchanged and identical in both modes.

## 5. Versioning and isolation (v1/v2 provably unchanged)

* `KNOWN_VERSIONS = ("v1", "v2", "v3")`; `PROTECTED_VERSIONS = ("v1", "v2")`; v3 writes only `logs/v3/<mode>/` and `results/v3/`. Running
  needs `--version v3`, as for v2.
* `make_policy(mode, "v3")` = v2 admission protocol + loan protocol; `run_one` builds `Engine(..., staff_loans=True)`. For
  every other version the loan code is never reached (a boolean flag, default off).
* **No change to existing serialisation.** New optional fields (`ProposedAction.loan`, `AgentMessage.sender_instance/recipient_instance/sender_id/recipient_id`) are omitted
  from dumps when `None`; `SimulationState.staff_loans` is declared `exclude=True`. v1/v2 state fingerprints, prompts, cache keys, and log lines stay byte-identical.
  Loans change `on_shift`, `hospital_id` and `treatment_slots`, which only happens in v3 runs.
* **Frozen prompts untouched** (`prompts.py`, `assessment.py`, `admission.py` instructions). v3 prompts live in a new module `agents/loans.py`.
* `eval/metrics.py`: loan/`LN-` messages are excluded from the conflict counters (as `ADM-` already is); new `RunMetrics` fields have defaults.

**Tests proving v1/v2 unchanged** (no network, nothing written under results/ or logs/):
1. golden test: `state_fingerprint` and the v2 dispatch/destination/reviewer prompts for fixed states equal stored values;
2. golden JSON of `ProposedAction` and `AgentMessage` dumps for the old action/message types;
3. in-memory naive and greedy runs on all scenarios/seeds-sample reproduce the rows in `results/v1` and `results/v2` field by field;
4. `git diff --exit-code final-submission -- results/v1 results/v2 logs/v1 logs/v2` (skipped if the tag is absent, e.g. CI);
5. `require_writable("v2")` raises; `run_one(..., "v3")` writes only under `*/v3/`;
6. a cached `agents` rerun of one v2 run (bottleneck 42) in memory with the LLM replaced by a function that raises on a cache miss: the metrics equal the
   saved row. **Zero tokens by construction; I will ask before running it** per CLAUDE.md.

## 6. Changes per file

| File | Change |
|---|---|
| `config.py` | add `v3`; protect `v2`; loan constants (`MIN/MAX_LOAN_MIN` 20/60, `MAX_TEAMS` 2, `STAFF_LOAN_N_MIN` 10 for metrics) |
| `models/messages.py` | `ActionType.LOAN_STAFF`; `LoanSpec` (lender, borrower, capability, teams, duration, staff_ids, serves); optional `loan` on `ProposedAction`; instance fields on `AgentMessage`; self-message rule relaxed only for distinct instances; new rejection reasons |
| `models/entities.py`, `models/state.py` | `LoanRecord`; `SimulationState.staff_loans` (excluded from dumps); `replay_view` adds loans only when one exists |
| `sim/validator.py` | `_check_loan` (section 2) |
| `sim/engine.py` | `staff_loans` flag; `LoanJob`; `_advance_loans`; trigger in `_decision_signature`; `_apply` for `LOAN_STAFF` |
| `sim/loans.py` (new) | trigger, candidate lenders, hard-rule check, staff picking (pure Python, shared by validator, engine, agents) |
| `agents/loans.py` (new) | ledger, fixed rule, the per-hospital instance prompts and structured outputs, `LoanProtocol` |
| `agents/system.py` | `loan_protocol` flag; one call after admissions; messages through existing helpers |
| `eval/experiment.py`, `scripts/run.py` | v3 wiring |
| `eval/metrics.py` | loan counters; treatment-wait metrics (section 7); `LN-` excluded from conflict counters |
| `dashboard/*`, `scripts/analysis.py` | later phase (section 9) |
| **Not touched** | scenarios, `data/`, `prompts.py`, `assessment.py`, v2 `admission.py`, `policies/*`, `deterioration.py`, `travel.py`, existing results and logs |

## 7. Pre-registered metrics (fixed before any v3 run)

Definitions use ground truth for evaluation only (as the primary CSR does). *Hospital arrival* `a_v` = minute of the
`handover_complete` event that contains the victim. *Treatment start* `s_v` = minute of `treatment_started`. *Critical* = severity 4-5.
The same function computes them from any log, so v3 rows and the saved v2 logs are measured identically.

| | metric | definition |
|---|---|---|
| **P1 (primary)** | critical treated within N | N = **10** min. Share of **all** critical victims in the run whose treatment started within 10 min of hospital arrival. A critical victim who never reaches a hospital, or never starts treatment, counts as not treated in time. |
| **P2 (primary)** | mean critical treatment wait | mean of `s_v - a_v` over critical victims whose treatment **started**; reported together with **critical never started** (a separate count that includes victims who never reached a hospital), so selection effects are visible. |
| S1 | critical service rate (first contact within deadline) | existing primary metric of v1/v2; **no-harm check**, loans do not move ambulances, so large changes would signal indirect effects |
| S2 | treatment started rate; critical admitted-but-never-started count | |
| S3 | loan activity | loan requests, accepted, rejected, countered, counters accepted, rounds, arbitrated, fallbacks, loans executed, team-minutes lent, slot-minutes transferred |
| S4 | cost | tokens, fresh tokens, model calls, list-price USD per run |
| S5 | sensitivity | P1 with N = 5 and 15; all P1/P2 without seed 42 |

**Contrasts** (paired by seed and scenario, 95% t-interval on the mean paired difference plus the exact sign-flip permutation p, as in
`01_rq1_permutation`):
* **C1, effect of loans:** v3 `agents` minus v2 `agents`; and v3 `negotiation` minus v2 `negotiation` (secondary).
* **C2, effect of negotiation on loans:** v3 `negotiation` minus v3 `agents`.

**Confirmatory family:** P1 and P2 x surge x {C1, C2} (agents-based) = 4 tests, Holm-corrected at 0.05. Direction stated beforehand: C1 raises P1 and
lowers P2 in surge. For C2 no direction is claimed (v2 found negotiation rarely binding). **Everything else, including
bottleneck, normal and S1-S5, is exploratory and labelled so**, with no multiplicity correction, as the secondary metrics in `RESULTS.md`.
A null result is a reportable result. Seeds: surge 42-51, bottleneck 42-46 (normal not run).

### Pre-freeze change (dev seed surge 42, before `v3-frozen`)

The first definitions used only critical victims who reached a hospital (P1 denominator) and censored never-started victims in P2. The surge 42 dev check
showed why that is misleading: v3 got fewer critical victims to hospital than v2 (11 -> 8, after the runs diverged at the first loan), so a
rate computed over hospital arrivals compares different groups of patients. Amended before any full run: P1's denominator is all critical victims, and P2 is the mean
over treated victims with `critical never started` reported separately. No result from the full grid existed when this was changed.

## 8. Token budget and checkpoints

v2 means per run (`results/v2`): surge agents 121k / negotiation 136k logical tokens, normal 79k / 90k, bottleneck 44k / 49k. The v3 loan calls
add a call only when a trigger fires (est. +5-15%). v3 runs diverge from v2 at their first loan, so less of the v2 cache is reusable than v2 had of v1's;
`negotiation` still reuses `agents` until its first differing decision. Rough fresh-token estimate: **surge 10 seeds x 2 modes ~ 1.2-1.6M, bottleneck 5 seeds ~ 0.2M** (to be re-estimated from the dev seed); normal is out of scope tonight. Surge plus bottleneck fit one day of the ~2.5M allowance.

Order of work and stops: (1) this design, **stop**; (2) code + tests, all 111+ existing tests green; (3) dev-seed run, surge 42, `agents` then `negotiation`, `--version v3`
(about 0.3M tokens), show the admission and loan chains and token use, **stop**; (4) tag `v3-frozen`, give you the exact commands for surge (10 seeds)
and bottleneck (5 seeds); (5) after your runs: analysis, `RESULTS.md` v3 section, dashboard (loan events in feed and negotiation explorer, loaned
staff on hospital cards, v3 in the version picker), README, **stop**.

## 9. Risks

* **Effect built in by assumption** (decision 1): the benefit is conditional on the +1 slot rule; stated wherever v3 is cited.
* **Small expected effect.** Most queue waits are short; the best case is the few critical patients per surge run who never start treatment. With 10 seeds the CI can be wide.
* **Lender harm.** A lent slot and team can leave the lender short for future arrivals; the hard rules protect only what it already holds (the lender instance and the fixed rule protect incoming critical patients). Reported through the lender's treatment wait (exploratory).
* **Few loan routes.** Slots by care type: trauma at H-T (3) and H-G (1), burn only at H-B, general everywhere. Burn loans are impossible, trauma loans run mainly H-G -> H-T (H-G can lend its single trauma slot only when it has no trauma patient queued or en route), and general loans mostly from H-G. The effect is therefore limited to those routes.
* **Transfer cost.** 12-16 minutes each way against a 20-60 minute loan; short loans may be wasteful, and the lender reviewer can counter with shorter terms.
* **Trigger noise.** Many hospital-minutes qualify; the in-flight accounting and the 20-minute minimum keep requests from repeating each minute.
* **Cache divergence** from v2 makes v3 runs cost more fresh tokens than v2 did.
* **Self-comparison.** v3 vs v2 mixes the loan effect with LLM noise after divergence; C1 uses the same seeds, and the no-harm metric S1 is shown.
* **One run per seed**; run-to-run LLM variance is not measured, as before.
