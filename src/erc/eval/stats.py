"""Statistics across seeds: summaries with 95% confidence intervals, and paired comparisons.

Every system runs on the same seeds, so differences between systems are
compared seed by seed (paired), which removes scenario-to-scenario noise.
"""
from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel

# Two-sided 95% critical values of Student's t distribution by degrees of freedom
_T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
         9: 2.262, 10: 2.228, 12: 2.179, 15: 2.131, 20: 2.086, 25: 2.060, 30: 2.042}


def t_critical(df: int) -> float:
    """Conservative: uses the nearest tabulated df at or below the requested one."""
    if df < 1:
        return float("nan")
    if df > 30:
        return 1.96
    return _T975[max(k for k in _T975 if k <= df)]


class Summary(BaseModel):
    n: int
    mean: float | None = None
    std: float | None = None
    median: float | None = None
    p95: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None


def summarize(values: list[float | None]) -> Summary:
    xs = np.array([float(v) for v in values if v is not None])
    if xs.size == 0:
        return Summary(n=0)
    mean = float(xs.mean())
    base = dict(n=int(xs.size), mean=mean, median=float(np.median(xs)), p95=float(np.percentile(xs, 95)))
    if xs.size == 1:
        return Summary(**base, std=0.0)
    std = float(xs.std(ddof=1))
    half = t_critical(xs.size - 1) * std / math.sqrt(xs.size)
    return Summary(**base, std=std, ci_low=mean - half, ci_high=mean + half)


class PairedComparison(BaseModel):
    n: int
    mean_diff: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    wins: int = 0
    losses: int = 0
    ties: int = 0

    @property
    def significant(self) -> bool:
        """True if the 95% CI of the difference excludes zero."""
        return self.ci_low is not None and (self.ci_low > 0 or self.ci_high < 0)


def paired_comparison(a: list[float | None], b: list[float | None]) -> PairedComparison:
    """Seed-by-seed difference a - b. Both lists must cover the same seeds in the same order."""
    if len(a) != len(b):
        raise ValueError("Paired comparison needs one value per seed for both systems")
    diffs = [x - y for x, y in zip(a, b) if x is not None and y is not None]
    s = summarize(diffs)
    return PairedComparison(n=s.n, mean_diff=s.mean, ci_low=s.ci_low, ci_high=s.ci_high,
                            wins=sum(d > 0 for d in diffs), losses=sum(d < 0 for d in diffs),
                            ties=sum(d == 0 for d in diffs))