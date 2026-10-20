"""Physics baseline: time for the mean motion to reach the ~180 km value at the current decay rate.

OMM MEAN_MOTION_DOT is half the first derivative of mean motion (rev/day²), so
t ≈ (n_crit - n) / (2 * MEAN_MOTION_DOT). Biased by design: drag grows as the orbit decays, so this
overestimates lifetime. It is the bar the model has to beat.
"""

from __future__ import annotations

import numpy as np

from kessler.orbits.elements import mean_motion_for_altitude

N_CRIT = mean_motion_for_altitude(180.0)  # ≈ 16.35 rev/day


def baseline_days(n, mmdot, cap: float = 365.0):
    n = np.asarray(n, dtype=float)
    mmdot = np.asarray(mmdot, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (N_CRIT - n) / (2 * mmdot)
    t = np.where((mmdot > 0) & np.isfinite(t), t, cap)
    return np.clip(t, 0.01, cap)
