"""Reference frames: TEME -> ECEF (GMST rotation) -> geodetic, and RTN (radial/transverse/normal)."""

from __future__ import annotations

import numpy as np

WGS84_A = 6378.137
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)
OMEGA_EARTH = 7.292115146706979e-5  # rad/s


def gmst_rad(jd_ut1) -> np.ndarray:
    """IAU-82 Greenwich mean sidereal time (Vallado `gstime`), radians in [0, 2π)."""
    jd = np.asarray(jd_ut1, dtype=float)
    t = (jd - 2451545.0) / 36525.0
    sec = -6.2e-6 * t**3 + 0.093104 * t**2 + (876600.0 * 3600 + 8640184.812866) * t + 67310.54841
    return np.mod(np.radians(sec / 240.0), 2 * np.pi)


def teme_to_ecef(r_teme, jd_ut1) -> np.ndarray:
    """Rotate TEME position(s) (..., 3) into the pseudo-Earth-fixed frame (polar motion ignored)."""
    r = np.asarray(r_teme, dtype=float)
    th = gmst_rad(jd_ut1)
    c, s = np.cos(th), np.sin(th)
    x = c * r[..., 0] + s * r[..., 1]
    y = -s * r[..., 0] + c * r[..., 1]
    return np.stack([x, y, r[..., 2]], axis=-1)


def ecef_to_geodetic(r_ecef) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """WGS-84 geodetic latitude/longitude (deg) and height (km); Bowring's method, 3 iterations."""
    r = np.asarray(r_ecef, dtype=float)
    x, y, z = r[..., 0], r[..., 1], r[..., 2]
    lon = np.arctan2(y, x)
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1 - WGS84_E2))
    for _ in range(5):
        n = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat) ** 2)
        lat = np.arctan2(z + WGS84_E2 * n * np.sin(lat), p)
    n = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat) ** 2)
    # height formula that is well conditioned at both the equator and the poles
    h = p * np.cos(lat) + z * np.sin(lat) - WGS84_A**2 / n
    return np.degrees(lat), np.degrees(lon), h


def teme_to_geodetic(r_teme, jd_ut1):
    return ecef_to_geodetic(teme_to_ecef(r_teme, jd_ut1))


def rtn_basis(r, v) -> np.ndarray:
    """Rows are unit vectors R (radial), T (transverse, along-track), N (orbit normal)."""
    r = np.asarray(r, dtype=float)
    v = np.asarray(v, dtype=float)
    R = r / np.linalg.norm(r, axis=-1, keepdims=True)
    h = np.cross(r, v)
    N = h / np.linalg.norm(h, axis=-1, keepdims=True)
    T = np.cross(N, R)
    return np.stack([R, T, N], axis=-2)


def to_rtn(vec, r_ref, v_ref) -> np.ndarray:
    """Express vector(s) in the RTN frame of the reference state."""
    B = rtn_basis(r_ref, v_ref)
    return np.einsum("...ij,...j->...i", B, np.asarray(vec, dtype=float))


def argument_of_latitude_deg(r, v) -> float:
    """Angle from the ascending node to the position vector, measured in the orbit plane."""
    r = np.asarray(r, dtype=float)
    h = np.cross(r, v)
    node = np.cross([0.0, 0.0, 1.0], h)
    if np.linalg.norm(node) < 1e-12:
        return float("nan")
    node /= np.linalg.norm(node)
    u = np.arccos(np.clip(np.dot(node, r) / np.linalg.norm(r), -1, 1))
    if r[2] < 0:
        u = 2 * np.pi - u
    return float(np.degrees(u))
