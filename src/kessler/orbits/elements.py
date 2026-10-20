"""Classical quantities derived from OMM mean elements (plan §7.1)."""

from __future__ import annotations

import numpy as np

MU = 398600.4418  # km^3/s^2
R_EARTH = 6378.137  # km (WGS-84 equatorial)
SECONDS_PER_DAY = 86400.0


def mean_motion_rad_s(n_rev_day):
    return np.asarray(n_rev_day, dtype=float) * 2 * np.pi / SECONDS_PER_DAY


def semi_major_axis_km(n_rev_day):
    n = mean_motion_rad_s(n_rev_day)
    return (MU / n**2) ** (1.0 / 3.0)


def apogee_alt_km(n_rev_day, ecc):
    return semi_major_axis_km(n_rev_day) * (1 + np.asarray(ecc, dtype=float)) - R_EARTH


def perigee_alt_km(n_rev_day, ecc):
    return semi_major_axis_km(n_rev_day) * (1 - np.asarray(ecc, dtype=float)) - R_EARTH


def period_min(n_rev_day):
    return 1440.0 / np.asarray(n_rev_day, dtype=float)


def mean_motion_for_altitude(alt_km: float) -> float:
    """Circular-orbit mean motion (rev/day) at a given altitude; e.g. ~16.4 rev/day at 180 km."""
    a = R_EARTH + alt_km
    n = np.sqrt(MU / a**3)
    return float(n * SECONDS_PER_DAY / (2 * np.pi))


def raan_rate_deg_day(n_rev_day, ecc, inc_deg):
    """Secular J2 nodal regression rate (deg/day)."""
    J2 = 1.08262668e-3
    a = semi_major_axis_km(n_rev_day)
    n = mean_motion_rad_s(n_rev_day)
    e = np.asarray(ecc, dtype=float)
    p = a * (1 - e**2)
    rate = -1.5 * J2 * (R_EARTH / p) ** 2 * n * np.cos(np.radians(inc_deg))
    return np.degrees(rate) * SECONDS_PER_DAY


def argp_rate_deg_day(n_rev_day, ecc, inc_deg):
    """Secular J2 apsidal rotation rate (deg/day)."""
    J2 = 1.08262668e-3
    a = semi_major_axis_km(n_rev_day)
    n = mean_motion_rad_s(n_rev_day)
    e = np.asarray(ecc, dtype=float)
    p = a * (1 - e**2)
    i = np.radians(inc_deg)
    rate = 0.75 * J2 * (R_EARTH / p) ** 2 * n * (5 * np.cos(i) ** 2 - 1)
    return np.degrees(rate) * SECONDS_PER_DAY
