"""Travel time model: grid distance x reproducible traffic factor.

The traffic factor depends only on (seed, origin cell, destination cell, time
window), never on which system is running. The same trip at the same time
takes the same time under every policy, which keeps comparisons fair.
"""
from __future__ import annotations

import hashlib
import math

from erc.config import SETTINGS
from erc.models.entities import Location

TRAFFIC_WINDOW_MIN = 15


def traffic_factor(seed: int, origin: Location, destination: Location, time_min: int) -> float:
    key = (f"{seed}|{int(origin.x)},{int(origin.y)}|"
           f"{int(destination.x)},{int(destination.y)}|{time_min // TRAFFIC_WINDOW_MIN}")
    u = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    t = SETTINGS.travel
    return t.traffic_factor_min + u * (t.traffic_factor_max - t.traffic_factor_min)


def travel_time_min(seed: int, origin: Location, destination: Location, time_min: int) -> int:
    distance = origin.distance_to(destination)
    if distance == 0:
        return 0
    minutes = distance / SETTINGS.travel.ambulance_speed_kmh * 60
    return max(1, math.ceil(minutes * traffic_factor(seed, origin, destination, time_min)))