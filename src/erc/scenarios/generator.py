"""Synthetic scenario generator.

Creates the TRUE state of the world for one scenario type and one seed:
fixed infrastructure (hospitals, ambulances, responders, staff) plus randomly
drawn incidents. The same (scenario, seed) always produces the identical scenario.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from erc.config import SCENARIO_DIR, SCENARIOS, SETTINGS, ScenarioConfig, ScenarioName, seeds_for
from erc.models.entities import (
    Ambulance, AmbulanceType, Capability, Hospital, Incident, IncidentType, Location,
    ResponderTeam, ResponderType, Severity, SkillLevel, StaffMember, StaffRole, Victim,
)
from erc.models.state import Scenario

# ───────── Fixed infrastructure: the city does not change between seeds ─────────
HOSPITAL_SPECS = [
    dict(hospital_id="H-T", name="Trauma Center", x=5.0, y=15.0, er_capacity=6,
         treatment_slots={Capability.TRAUMA: 3, Capability.GENERAL: 1}, beds=10),
    dict(hospital_id="H-B", name="Burn Unit", x=15.0, y=13.0, er_capacity=5,
         treatment_slots={Capability.BURN: 3, Capability.GENERAL: 1}, beds=8),
    dict(hospital_id="H-G", name="General Hospital", x=10.0, y=4.0, er_capacity=8,
         treatment_slots={Capability.GENERAL: 4, Capability.TRAUMA: 1}, beds=14),
]
SPECIALTY = {"H-T": Capability.TRAUMA, "H-B": Capability.BURN, "H-G": Capability.GENERAL}
SECONDARY = {"H-T": Capability.GENERAL, "H-B": Capability.GENERAL, "H-G": Capability.TRAUMA}

# Ordered so that taking ambulances out of service from the end keeps an ALS/BLS mix
AMBULANCE_SPECS = [
    ("AMB-01", AmbulanceType.ALS, 6.0, 13.0),
    ("AMB-02", AmbulanceType.BLS, 14.0, 6.0),
    ("AMB-03", AmbulanceType.ALS, 16.0, 15.0),
    ("AMB-04", AmbulanceType.BLS, 4.0, 5.0),
    ("AMB-05", AmbulanceType.BLS, 10.0, 10.0),
]
RESPONDER_SPECS = [
    ("FIRE-1", ResponderType.FIRE, 12.0, 12.0),
    ("RESCUE-1", ResponderType.RESCUE, 7.0, 8.0),
    ("MED-1", ResponderType.MEDICAL, 13.0, 3.0),
]

# What each incident type typically needs
INCIDENT_PROFILES = {
    IncidentType.VEHICLE_COLLISION: dict(weight=0.35, capability=Capability.TRAUMA,
                                         responder=ResponderType.RESCUE, victims=(1, 4)),
    IncidentType.BUILDING_FIRE: dict(weight=0.20, capability=Capability.BURN,
                                     responder=ResponderType.FIRE, victims=(1, 5)),
    IncidentType.STRUCTURAL_COLLAPSE: dict(weight=0.10, capability=Capability.TRAUMA,
                                           responder=ResponderType.RESCUE, victims=(2, 5)),
    IncidentType.INDUSTRIAL_ACCIDENT: dict(weight=0.10, capability=Capability.BURN,
                                           responder=ResponderType.FIRE, victims=(1, 3)),
    IncidentType.MEDICAL_EMERGENCY: dict(weight=0.25, capability=Capability.GENERAL,
                                         responder=None, victims=(1, 1)),
}
SCENARIO_INDEX = {name: i for i, name in enumerate(ScenarioName)}


def _loc(x: float, y: float) -> Location:
    return Location(x=x, y=y)


# ───────── Builders ─────────
def _build_hospitals(trauma_prefill: float) -> list[Hospital]:
    hospitals = []
    for spec in HOSPITAL_SPECS:
        s = dict(spec)
        x, y = s.pop("x"), s.pop("y")
        h = Hospital(location=_loc(x, y), **s)
        if trauma_prefill > 0 and h.hospital_id == "H-T":
            busy = int(round(trauma_prefill * h.treatment_slots[Capability.TRAUMA]))
            h.treatment_occupied = {Capability.TRAUMA: busy}
            h.beds_occupied = busy
        hospitals.append(h)
    return hospitals


def _skills(hospital_id: str, top: SkillLevel, second: SkillLevel) -> dict[Capability, SkillLevel]:
    skills = {c: SkillLevel.BASIC for c in Capability}
    skills[SECONDARY[hospital_id]] = second
    skills[SPECIALTY[hospital_id]] = top
    return skills


def _build_staff() -> list[StaffMember]:
    staff, d, n = [], 0, 0
    per_hospital_doctors = SETTINGS.env.n_doctors // len(SPECIALTY)
    per_hospital_nurses = SETTINGS.env.n_nurses // len(SPECIALTY)
    for hid in SPECIALTY:
        for _ in range(per_hospital_doctors):
            d += 1
            staff.append(StaffMember(staff_id=f"D-{d:02d}", role=StaffRole.DOCTOR, hospital_id=hid,
                                     skills=_skills(hid, SkillLevel.EXPERT, SkillLevel.INTERMEDIATE),
                                     max_patients=3))
        for _ in range(per_hospital_nurses):
            n += 1
            staff.append(StaffMember(staff_id=f"N-{n:02d}", role=StaffRole.NURSE, hospital_id=hid,
                                     skills=_skills(hid, SkillLevel.INTERMEDIATE, SkillLevel.BASIC),
                                     max_patients=2))
    return staff


def _build_ambulances(out_of_service: int) -> list[Ambulance]:
    n = SETTINGS.env.n_ambulances - out_of_service
    return [Ambulance(ambulance_id=aid, ambulance_type=t, capacity=SETTINGS.env.ambulance_capacity,
                      location=_loc(x, y), base_location=_loc(x, y))
            for aid, t, x, y in AMBULANCE_SPECS[:n]]


def _build_responders() -> list[ResponderTeam]:
    return [ResponderTeam(team_id=tid, responder_type=t, location=_loc(x, y), base_location=_loc(x, y))
            for tid, t, x, y in RESPONDER_SPECS]


def _draw_incidents(rng: np.random.Generator, cfg: ScenarioConfig) -> list[Incident]:
    types = list(INCIDENT_PROFILES)
    type_p = [INCIDENT_PROFILES[t]["weight"] for t in types]
    arrivals = np.sort(rng.integers(0, cfg.arrival_window_min, size=cfg.n_incidents))
    incidents = []
    for k, arrival in enumerate(arrivals, start=1):
        iid = f"INC-{k:02d}"
        itype = types[int(rng.choice(len(types), p=type_p))]
        prof = INCIDENT_PROFILES[itype]
        lo, hi = prof["victims"]
        victims = []
        for j in range(1, int(rng.integers(lo, hi + 1)) + 1):
            sev = Severity(int(rng.choice(5, p=cfg.severity_weights)) + 1)
            # Serious cases usually need the incident's specialty; minor ones need general care
            specialty = sev >= Severity.SERIOUS and rng.random() < 0.8
            cap = prof["capability"] if specialty else Capability.GENERAL
            d_lo, d_hi = SETTINGS.deterioration.deadline_range_min[int(sev)]
            victims.append(Victim(victim_id=f"V-{k:02d}-{j}", incident_id=iid, severity=sev,
                                  required_capability=cap, needs_als=sev >= Severity.SEVERE,
                                  deadline_min=int(rng.integers(d_lo, d_hi + 1))))
        location = _loc(round(float(rng.uniform(0.5, 19.5)), 1), round(float(rng.uniform(0.5, 19.5)), 1))
        incidents.append(Incident(incident_id=iid, incident_type=itype, location=location,
                                  arrival_time_min=int(arrival), victims=victims,
                                  required_responder=prof["responder"]))
    return incidents


# ───────── Public API ─────────
def generate_scenario(name: ScenarioName, seed: int) -> Scenario:
    cfg = SCENARIOS[name]
    rng = np.random.default_rng([seed, SCENARIO_INDEX[name]])
    return Scenario(
        name=name, seed=seed,
        hospitals=_build_hospitals(cfg.trauma_prefill),
        ambulances=_build_ambulances(cfg.ambulances_out_of_service),
        responders=_build_responders(),
        staff=_build_staff(),
        incidents=_draw_incidents(rng, cfg),
    )


def generate_all(directory: Path = SCENARIO_DIR) -> list[Path]:
    return [generate_scenario(name, seed).save(directory)
            for name in ScenarioName for seed in seeds_for(name)]


if __name__ == "__main__":
    paths = generate_all()
    print(f"Generated {len(paths)} scenarios in {SCENARIO_DIR}")