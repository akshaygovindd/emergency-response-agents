"""Synthetic patient deterioration. A simulation device, not a medical model.

Each victim loses condition at a constant rate, calibrated so that condition
reaches the critical threshold exactly at that victim's deadline if no crew
arrives. A crew on scene or in transport slows decline by a care factor
(ALS much more than BLS). Decline stops once hospital treatment starts.
"""
from __future__ import annotations

from erc.config import SETTINGS
from erc.models.entities import Victim, VictimStatus

_EPS = 1e-9


def loss_rate(victim: Victim) -> float:
    """Condition points lost per minute for this victim with no care."""
    return (100.0 - SETTINGS.deterioration.critical_threshold) / victim.deadline_min


def deteriorate(victim: Victim, minutes: int = 1, care_factor: float = 1.0) -> None:
    """care_factor: 1.0 = no crew, SETTINGS.deterioration.bls/als_care_factor = crew present."""
    if victim.status in (VictimStatus.IN_TREATMENT, VictimStatus.TREATED):
        return
    victim.condition = max(0.0, victim.condition - loss_rate(victim) * care_factor * minutes)


def is_deteriorated(victim: Victim) -> bool:
    return victim.condition < SETTINGS.deterioration.critical_threshold - _EPS