"""v3 staff loans: the pure-Python rules every part of the system shares.

A loan moves one treatment slot of a care type AND one doctor + nurse team per team from a lender
hospital to a borrower hospital for a while. The validator, the engine's trigger, and the agents'
protocol all use the functions here, so they can never disagree about what is allowed.
Nothing in this module changes state; the engine applies loans (sim/engine.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from erc.config import SETTINGS
from erc.models.entities import (
    Capability, Hospital, LoanPhase, SkillLevel, StaffMember, StaffRole, Victim, VictimStatus,
)
from erc.models.messages import LoanSpec, RejectionReason, ValidationResult
from erc.models.state import SimulationState

R = RejectionReason
DOCTOR_MIN, NURSE_MIN = SkillLevel.INTERMEDIATE, SkillLevel.BASIC     # same thresholds as treatment (engine)


def _ok() -> ValidationResult:
    return ValidationResult(accepted=True)


def _no(reason: RejectionReason, detail: str) -> ValidationResult:
    return ValidationResult(accepted=False, reason=reason, detail=detail)


@dataclass
class Ledger:
    """Promises made earlier in the same negotiation round, so one slot or one person is never lent twice."""
    slots_out: dict[tuple[str, Capability], int] = field(default_factory=dict)
    slots_in: dict[tuple[str, Capability], int] = field(default_factory=dict)
    staff: set[str] = field(default_factory=set)

    def reserve(self, spec: LoanSpec, doctors: list[str], nurses: list[str]) -> None:
        out, into = (spec.lender_id, spec.capability), (spec.borrower_id, spec.capability)
        self.slots_out[out] = self.slots_out.get(out, 0) + spec.teams
        self.slots_in[into] = self.slots_in.get(into, 0) + spec.teams
        self.staff |= {*doctors, *nurses}


# ───────── Views of the hospital queue ─────────
def queued(state: SimulationState, hospital_id: str, cap: Capability) -> list[Victim]:
    """Victims in this hospital's ER waiting for treatment of this care type."""
    return [v for v in state.victims()
            if v.status == VictimStatus.AWAITING_TREATMENT and state.admissions.get(v.victim_id) == hospital_id
            and v.required_capability == cap]


def incoming(state: SimulationState, hospital_id: str, cap: Capability | None = None) -> list[Victim]:
    """Victims admitted to this hospital who have not arrived yet."""
    en_route = (VictimStatus.WAITING, VictimStatus.IN_TRANSPORT)
    out = []
    for vid, hid in state.admissions.items():
        v = state.find_victim(vid)
        if hid == hospital_id and v is not None and v.status in en_route and (cap is None or v.required_capability == cap):
            out.append(v)
    return out


def held_patients(state: SimulationState, hospital_id: str) -> int:
    """Patients a hospital already holds that still need treatment: queued in the ER plus en route."""
    waiting = sum(1 for v in state.victims()
                  if v.status == VictimStatus.AWAITING_TREATMENT and state.admissions.get(v.victim_id) == hospital_id)
    return waiting + len(incoming(state, hospital_id))


def on_loan_ids(state: SimulationState) -> set[str]:
    return {sid for ln in state.loans_in_flight() for sid in ln.staff_ids}


def teams_covering(state: SimulationState, borrower_id: str, cap: Capability) -> int:
    """Teams already on their way to (or working at) the borrower for this care type."""
    return sum(ln.teams for ln in state.loans_in_flight()
               if ln.borrower_id == borrower_id and ln.capability == cap
               and ln.phase in (LoanPhase.TRANSFER_OUT, LoanPhase.ACTIVE))


def _pending_slots(state: SimulationState, borrower_id: str) -> int:
    """Slots promised to the borrower but not yet open (loans still travelling)."""
    return sum(ln.teams for ln in state.loans_in_flight()
               if ln.borrower_id == borrower_id and ln.phase == LoanPhase.TRANSFER_OUT)


# ───────── Staff ─────────
def idle_staff(state: SimulationState, hospital_id: str, role: StaffRole, cap: Capability,
               exclude: set[str]) -> list[StaffMember]:
    """On-shift, idle, qualified staff of this hospital who are not on loan or promised, lowest id first."""
    minimum = DOCTOR_MIN if role == StaffRole.DOCTOR else NURSE_MIN
    return sorted((m for m in state.staff.values()
                   if m.hospital_id == hospital_id and m.role == role and m.on_shift and m.current_patients == 0
                   and m.staff_id not in exclude and m.is_qualified(cap, minimum)),
                  key=lambda m: m.staff_id)


def pick_staff(state: SimulationState, spec: LoanSpec, ledger: Ledger | None = None
               ) -> tuple[list[str], list[str]] | None:
    """The doctors and nurses a loan would take (lowest qualifying ids), or None if there are not enough."""
    exclude = on_loan_ids(state) | (ledger.staff if ledger else set())
    docs = idle_staff(state, spec.lender_id, StaffRole.DOCTOR, spec.capability, exclude)
    nurses = idle_staff(state, spec.lender_id, StaffRole.NURSE, spec.capability, exclude)
    if len(docs) < spec.teams or len(nurses) < spec.teams:
        return None
    return [m.staff_id for m in docs[:spec.teams]], [m.staff_id for m in nurses[:spec.teams]]


def _headroom(state: SimulationState, hospital_id: str, role: StaffRole, removed: set[str]) -> int:
    return sum(m.max_patients - m.current_patients for m in state.staff.values()
               if m.hospital_id == hospital_id and m.role == role and m.on_shift
               and m.staff_id not in removed and m.staff_id not in on_loan_ids(state))


def can_start_now(state: SimulationState, h: Hospital, cap: Capability) -> bool:
    """Mirror of the engine's treatment start test for one more patient of this care type."""
    if h.free_slots(cap) <= 0 or h.beds_occupied >= h.beds:
        return False
    return (any(m.hospital_id == h.hospital_id and m.role == StaffRole.DOCTOR and m.is_available
                and m.is_qualified(cap, DOCTOR_MIN) for m in state.staff.values())
            and any(m.hospital_id == h.hospital_id and m.role == StaffRole.NURSE and m.is_available
                    and m.is_qualified(cap, NURSE_MIN) for m in state.staff.values()))


# ───────── The hard rules ─────────
def uncovered_need(state: SimulationState, borrower_id: str, cap: Capability) -> int:
    """Queued patients for this care type that cannot start now and are not covered by a loan in flight."""
    h = state.hospitals[borrower_id]
    if not h.can_treat(cap) or can_start_now(state, h, cap):
        return 0
    return max(0, len(queued(state, borrower_id, cap)) - teams_covering(state, borrower_id, cap))


def check_loan(state: SimulationState, spec: LoanSpec, ledger: Ledger | None = None) -> ValidationResult:
    cfg, ledger = SETTINGS.loans, ledger or Ledger()
    lender, borrower = state.hospitals.get(spec.lender_id), state.hospitals.get(spec.borrower_id)
    if lender is None or borrower is None:
        return _no(R.UNKNOWN_RESOURCE, f"Unknown hospital in loan {spec.lender_id} -> {spec.borrower_id}")
    if lender.hospital_id == borrower.hospital_id:
        return _no(R.MALFORMED, "A hospital cannot lend to itself")
    if not 1 <= spec.teams <= cfg.max_teams:
        return _no(R.MALFORMED, f"teams must be 1..{cfg.max_teams}, got {spec.teams}")
    if not cfg.min_duration_min <= spec.duration_min <= cfg.max_duration_min:
        return _no(R.MALFORMED, f"duration must be {cfg.min_duration_min}..{cfg.max_duration_min} min")
    cap = spec.capability
    if not borrower.can_treat(cap):
        return _no(R.HOSPITAL_LACKS_CAPABILITY, f"{borrower.hospital_id} has no {cap.value} slot to add to")
    promised_in = ledger.slots_in.get((borrower.hospital_id, cap), 0)
    if spec.teams > uncovered_need(state, borrower.hospital_id, cap) - promised_in:
        return _no(R.LOAN_NOT_NEEDED, f"{borrower.hospital_id} has no uncovered {cap.value} queue for {spec.teams} team(s)")
    total_in = sum(n for (h, _), n in ledger.slots_in.items() if h == borrower.hospital_id)
    slots_after = sum(borrower.treatment_slots.values()) + _pending_slots(state, borrower.hospital_id) + total_in + spec.teams
    if slots_after > borrower.beds:
        return _no(R.BORROWER_BEDS_FULL, f"{borrower.hospital_id} would have {slots_after} slots for {borrower.beds} beds")
    promised_out = ledger.slots_out.get((lender.hospital_id, cap), 0)
    if lender.free_slots(cap) - promised_out < spec.teams:
        return _no(R.LENDER_NO_IDLE_SLOT, f"{lender.hospital_id} has no idle {cap.value} slot for {spec.teams} team(s)")
    picked = pick_staff(state, spec, ledger)
    if picked is None:
        return _no(R.STAFF_UNAVAILABLE, f"{lender.hospital_id} has no idle qualified doctor and nurse for {spec.teams} team(s)")
    removed = {*picked[0], *picked[1], *ledger.staff}
    remaining_slots = lender.treatment_slots.get(cap, 0) - promised_out - spec.teams
    if remaining_slots < 1 and (queued(state, lender.hospital_id, cap) or incoming(state, lender.hospital_id, cap)):
        return _no(R.LENDER_UNDERSTAFFED, f"{lender.hospital_id} still needs its last {cap.value} slot for its own patients")
    need = held_patients(state, lender.hospital_id)
    if (_headroom(state, lender.hospital_id, StaffRole.DOCTOR, removed) < need
            or _headroom(state, lender.hospital_id, StaffRole.NURSE, removed) < need):
        return _no(R.LENDER_UNDERSTAFFED, f"{lender.hospital_id} would not have staff left for the {need} patients it holds")
    return _ok()


# ───────── Triggers and candidates ─────────
def _minutes(a: Hospital, b: Hospital) -> int:
    """Travel estimate without traffic, as the agents see it."""
    return math.ceil(a.location.distance_to(b.location) * 60 / SETTINGS.travel.ambulance_speed_kmh)


@dataclass
class LoanNeed:
    borrower_id: str
    capability: Capability
    victim_ids: list[str]          # queued victims for this care type, most severe first (evaluation truth, used only by Python)
    uncovered: int
    lenders: list[str]             # lenders that pass every hard rule for one team, nearest first


def candidate_lenders(state: SimulationState, borrower_id: str, cap: Capability, ledger: Ledger | None = None,
                      teams: int = 1) -> list[str]:
    spec = lambda lid: LoanSpec(lender_id=lid, borrower_id=borrower_id, capability=cap, teams=teams,
                                duration_min=SETTINGS.loans.min_duration_min)
    b = state.hospitals[borrower_id]
    ok = [h for h in state.hospitals.values()
          if h.hospital_id != borrower_id and check_loan(state, spec(h.hospital_id), ledger).accepted]
    return [h.hospital_id for h in sorted(ok, key=lambda h: (_minutes(h, b), h.hospital_id))]


def open_needs(state: SimulationState, ledger: Ledger | None = None) -> list[LoanNeed]:
    """Every (borrower, care type) with an unmet queue AND at least one feasible lender."""
    needs = []
    for h in state.hospitals.values():
        for cap in h.treatment_slots:
            n = uncovered_need(state, h.hospital_id, cap)
            if n <= 0:
                continue
            lenders = candidate_lenders(state, h.hospital_id, cap, ledger)
            if lenders:
                q = sorted(queued(state, h.hospital_id, cap), key=lambda v: (-int(v.severity), v.condition, v.victim_id))
                needs.append(LoanNeed(h.hospital_id, cap, [v.victim_id for v in q], n, lenders))
    return needs
