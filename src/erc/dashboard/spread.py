"""Spread incident markers that sit too close together, so their glows and labels never overlap.

Display positions only: the true location stays in the data and in every calculation. Deterministic:
the same incidents always give the same display positions.
"""
from __future__ import annotations

import math

MIN_SEPARATION_KM = 1.9          # glow radius is about 0.9 km on the map
MAX_SHIFT_KM = 1.3               # a marker never moves further than this from its true place
GRID_KM = 20.0
EDGE_KM = 0.8                    # markers stay this far inside the grid edge so glows are not cut off


def spread_positions(points: list[tuple[float, float]], min_km: float = MIN_SEPARATION_KM,
                     max_shift_km: float = MAX_SHIFT_KM, iterations: int = 60) -> list[tuple[float, float]]:
    """Push close pairs apart (equal and opposite) until every pair is min_km apart, or the shift cap is reached."""
    pos = [list(p) for p in points]
    for _ in range(iterations):
        moved = False
        for i in range(len(pos)):
            for j in range(i + 1, len(pos)):
                dx, dy = pos[j][0] - pos[i][0], pos[j][1] - pos[i][1]
                d = math.hypot(dx, dy)
                if d >= min_km - 1e-6:
                    continue
                if d < 1e-9:                                  # identical spots: separate along a fixed direction
                    dx, dy, d = 1.0, 0.0, 1.0
                push = (min_km - d) / 2
                ux, uy = dx / d, dy / d
                pos[i][0] -= ux * push; pos[i][1] -= uy * push
                pos[j][0] += ux * push; pos[j][1] += uy * push
                moved = True
        for k, (x, y) in enumerate(pos):                      # cap the distance from the true place, stay on the grid
            tx, ty = points[k]
            shift = math.hypot(x - tx, y - ty)
            if shift > max_shift_km:
                x, y = tx + (x - tx) * max_shift_km / shift, ty + (y - ty) * max_shift_km / shift
            pos[k] = [min(GRID_KM - EDGE_KM, max(EDGE_KM, x)), min(GRID_KM - EDGE_KM, max(EDGE_KM, y))]
        if not moved:
            break
    return [(round(x, 2), round(y, 2)) for x, y in pos]
