"""Synthetic fragmentation generator (plan Phase 3 regression test).

Take a parent element set, apply random Δv kicks at a known time, turn each resulting state back into
an OMM-like element set and move it to a later "catalogue" epoch. The solver should recover the time
and the Δv distribution.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from kessler.orbits.frames import rtn_basis
from kessler.orbits.propagate import satrec_from_row, to_jd

MU = 398600.4418


def rv_to_elements(r: np.ndarray, v: np.ndarray) -> dict:
    """Classical elements (deg, rev/day) from a TEME state."""
    h = np.cross(r, v)
    hn = np.linalg.norm(h)
    rn = np.linalg.norm(r)
    node = np.cross([0, 0, 1.0], h)
    nn = np.linalg.norm(node)
    evec = np.cross(v, h) / MU - r / rn
    e = np.linalg.norm(evec)
    energy = np.dot(v, v) / 2 - MU / rn
    a = -MU / (2 * energy)
    inc = np.degrees(np.arccos(h[2] / hn))
    raan = np.degrees(np.arctan2(node[1], node[0])) % 360
    argp = np.degrees(np.arccos(np.clip(np.dot(node, evec) / (nn * e), -1, 1)))
    if evec[2] < 0:
        argp = 360 - argp
    nu = np.degrees(np.arccos(np.clip(np.dot(evec, r) / (e * rn), -1, 1)))
    if np.dot(r, v) < 0:
        nu = 360 - nu
    E = 2 * np.arctan(np.sqrt((1 - e) / (1 + e)) * np.tan(np.radians(nu) / 2))
    M = np.degrees(E - e * np.sin(E)) % 360
    n = np.sqrt(MU / a**3) * 86400 / (2 * np.pi)
    return {"mean_motion": n, "eccentricity": e, "inclination": inc, "ra_of_asc_node": raan, "arg_of_pericenter": argp, "mean_anomaly": M}


ANGLES = ("inclination", "ra_of_asc_node", "arg_of_pericenter", "mean_anomaly")


def fit_mean_elements(template: pd.Series, r: np.ndarray, v: np.ndarray, epoch: pd.Timestamp, norad: int, name: str, iters: int = 40) -> dict:
    """SGP4 mean elements whose SGP4 state at ``epoch`` reproduces (r, v): fixed-point iteration
    on the osculating-element residual (the usual osculating-to-mean conversion)."""
    target = rv_to_elements(r, v)
    mean = dict(target)
    for _ in range(iters):
        row = _row(template, mean, epoch, norad, name)
        r1, v1 = _state(row, epoch)
        osc = rv_to_elements(r1, v1)
        err = 0.0
        for k in mean:
            d = target[k] - osc[k]
            if k in ANGLES or k == "mean_anomaly":
                d = (d + 180) % 360 - 180
            mean[k] = mean[k] + d
            if k in ANGLES:
                mean[k] %= 360
        mean["eccentricity"] = max(mean["eccentricity"], 1e-7)
        err = np.linalg.norm(r1 - r)
        if err < 1e-4:
            break
    return _row(template, mean, epoch, norad, name)


def _row(template: pd.Series, el: dict, epoch: pd.Timestamp, norad: int, name: str) -> dict:
    row = template.to_dict()
    row.update(el)
    row.update({"epoch": epoch, "norad_cat_id": norad, "object_name": name, "bstar": 0.0, "mean_motion_dot": 0.0, "mean_motion_ddot": 0.0})
    return row


def _state(row: dict, t: pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
    s = satrec_from_row(row)
    jd, fr = to_jd([t])
    e, r, v = s.sgp4(jd[0], fr[0])
    assert e == 0
    return np.array(r), np.array(v)


def make_breakup(parent: pd.Series, t_break: pd.Timestamp, n: int = 25, sigma_ms: float = 20.0, catalogue_after_days: float = 2.0, seed: int = 0, along_track_noise_km: float = 5.0):
    rng = np.random.default_rng(seed)
    base = parent.copy()
    base["bstar"] = 0.0
    base["mean_motion_dot"] = 0.0
    base["mean_motion_ddot"] = 0.0
    rp, vp = _state(base.to_dict(), t_break)
    p_row = base.to_dict()
    B = rtn_basis(rp, vp)
    dv_rtn = rng.normal(0, sigma_ms, size=(n, 3))
    later = t_break + pd.Timedelta(days=catalogue_after_days)
    frags = []
    for i in range(n):
        v = vp + (dv_rtn[i] / 1000.0) @ B
        row0 = fit_mean_elements(base, rp, v, t_break, 300000 + i, f"SYN DEB {i}")
        r1, v1 = _state(row0, later)
        row1 = fit_mean_elements(base, r1, v1, later, 300000 + i, f"SYN DEB {i}")
        # orbit-determination error: a random along-track offset of the catalogued element set
        a = (MU / (row1["mean_motion"] * 2 * np.pi / 86400) ** 2) ** (1 / 3)
        row1["mean_anomaly"] = (row1["mean_anomaly"] + np.degrees(rng.normal(0, along_track_noise_km) / a)) % 360
        frags.append(row1)
    parent_later = fit_mean_elements(base, *_state(p_row, later), later, int(parent["norad_cat_id"]), "PARENT")
    return pd.Series(parent_later), pd.DataFrame(frags), dv_rtn
