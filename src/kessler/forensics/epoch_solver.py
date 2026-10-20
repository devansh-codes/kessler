"""Breakup epoch and location (plan §7.2).

Two estimators are computed:

* ``sgp4-spread`` (the plan's method): back-propagate the parent and each fragment's earliest element
  set with SGP4 and find the time that minimises the median parent-fragment distance.
* ``orbit-crossing`` (robust alternative): at the true breakup time the parent's position lies on every
  fragment's orbit. We minimise the median distance from the parent's position to each fragment's
  osculating ellipse. This ignores along-track (timing) error, which dominates when fragments are only
  catalogued weeks after the event.

Both return a time curve, a bootstrap interval and quality flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

from kessler.orbits.frames import argument_of_latitude_deg, teme_to_geodetic
from kessler.orbits.propagate import propagate, satrec_from_row, to_jd

MU = 398600.4418


@dataclass
class Solution:
    method: str
    t_p05: pd.Timestamp | None = None
    t_p50: pd.Timestamp | None = None
    t_p95: pd.Timestamp | None = None
    spread_km: float | None = None
    n_used: int = 0
    lat: float | None = None
    lon: float | None = None
    alt_km: float | None = None
    arg_lat_deg: float | None = None
    flags: list[str] = field(default_factory=list)
    curve: list[dict] = field(default_factory=list)
    sensitivity: list[dict] = field(default_factory=list)
    crossings: list[dict] = field(default_factory=list)
    used_norads: list[int] = field(default_factory=list)
    excluded: dict[int, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        iso = lambda t: None if t is None else pd.Timestamp(t).isoformat()  # noqa: E731
        return {
            "method": self.method,
            "t_p05": iso(self.t_p05),
            "t_p50": iso(self.t_p50),
            "t_p95": iso(self.t_p95),
            "spread_km": None if self.spread_km is None else round(float(self.spread_km), 3),
            "n_used": self.n_used,
            "lat": _r(self.lat, 3),
            "lon": _r(self.lon, 3),
            "alt_km": _r(self.alt_km, 1),
            "arg_lat_deg": _r(self.arg_lat_deg, 2),
            "flags": self.flags,
            "curve": self.curve,
            "sensitivity": self.sensitivity,
            "crossings": self.crossings,
            "used_norads": self.used_norads,
            "excluded": {str(k): v for k, v in self.excluded.items()},
        }


def _r(v, d):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), d)


# --------------------------------------------------------------------------- objectives
def _states(rows: pd.DataFrame, times: pd.DatetimeIndex):
    p = propagate(rows, times)
    return p.r, p.v


def _point_to_orbit_km(P: np.ndarray, r: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Distance from point(s) P (..., 3) to the osculating ellipse defined by state (r, v) (..., 3)."""
    h = np.cross(r, v)
    hn = np.linalg.norm(h, axis=-1, keepdims=True)
    nhat = h / hn
    d_out = np.sum(P * nhat, axis=-1)
    Pp = P - d_out[..., None] * nhat
    rn = np.linalg.norm(r, axis=-1, keepdims=True)
    evec = np.cross(v, h) / MU - r / rn
    e = np.linalg.norm(evec, axis=-1)
    p = (hn[..., 0] ** 2) / MU
    Ppn = np.linalg.norm(Pp, axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        ehat = np.where(e[..., None] > 1e-9, evec / np.maximum(e[..., None], 1e-12), r / rn)
        cosnu = np.sum(Pp * ehat, axis=-1) / Ppn
    r_orbit = p / (1 + e * cosnu)
    d_in = Ppn - r_orbit
    return np.hypot(d_out, d_in)


def _median_curve(D: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        return np.nanmedian(D, axis=0)


# --------------------------------------------------------------------------- solver
def _local_minima(c: np.ndarray, order: int) -> np.ndarray:
    from scipy.signal import argrelmin

    filled = np.where(np.isfinite(c), c, np.nanmax(c[np.isfinite(c)]) if np.isfinite(c).any() else 0)
    idx = argrelmin(filled, order=max(order, 1), mode="clip")[0]
    return idx[np.isfinite(c[idx])]


def solve(
    parent: pd.Series,
    fragments: pd.DataFrame,
    ref_time: pd.Timestamp,
    method: str = "hybrid",
    window_days_before: float = 3.0,
    step_s: float = 20.0,
    n_boot: int = 300,
    low_conf_km: float = 200.0,
    min_fragments: int = 3,
    second_sets: pd.DataFrame | None = None,
    references: list[tuple[str, pd.Timestamp]] | None = None,
    seed: int = 7,
) -> Solution:
    """Solve for the breakup epoch.

    ``method``: ``hybrid`` (default: SGP4 spread selects the orbit, orbit crossing fixes the time within
    it), ``sgp4-spread`` (plan §7.2 as written) or ``orbit-crossing`` (global crossing minimum).
    """
    sol = Solution(method=method)
    frags = fragments.reset_index(drop=True)
    if len(frags) == 0:
        sol.flags.append("NO_PUBLIC_FRAGMENTS")
        return sol
    if len(frags) < min_fragments:
        sol.flags.append("FEW_FRAGMENTS")

    ref_time = pd.Timestamp(ref_time)
    first_epoch = pd.Timestamp(frags["epoch"].min())
    start = ref_time - pd.Timedelta(days=window_days_before)
    end = min(first_epoch, ref_time + pd.Timedelta(days=window_days_before))
    if end <= start + pd.Timedelta(hours=6):
        end = start + pd.Timedelta(days=2 * window_days_before)
    grid = pd.date_range(start, end, freq=pd.Timedelta(seconds=step_s))
    period_s = 86400.0 / float(parent["mean_motion"])
    order = int(0.4 * period_s / step_s)

    spread_obj = _make_objective(parent, frags, "sgp4-spread")
    cross_obj = _make_objective(parent, frags, "orbit-crossing")
    Ds = spread_obj(grid)
    Dc = cross_obj(grid)
    if np.all(np.isnan(Ds)) or np.all(np.isnan(Dc)):
        sol.flags.append("PROPAGATION_FAILED")
        return sol

    def estimate(idx: np.ndarray) -> tuple[int, int] | None:
        cs = np.nanmedian(Ds[idx], axis=0)
        cc = np.nanmedian(Dc[idx], axis=0)
        if np.all(np.isnan(cs)):
            return None
        k_s = int(np.nanargmin(cs))
        if method == "sgp4-spread":
            return k_s, k_s
        mins = _local_minima(cc, order)
        if len(mins) == 0:
            return k_s, int(np.nanargmin(cc))
        if method == "orbit-crossing":
            return k_s, int(mins[np.argmin(cc[mins])])
        return k_s, int(mins[np.argmin(np.abs(mins - k_s))])

    all_idx = np.arange(len(frags))
    with np.errstate(all="ignore"):
        est = estimate(all_idx)
    if est is None:
        sol.flags.append("PROPAGATION_FAILED")
        return sol

    # outliers: fragments whose orbit misses the parent's position at t* by > 3x the median (and > 25 km)
    k = est[1]
    miss = Dc[:, k]
    med = np.nanmedian(miss)
    bad = np.where((miss > 3 * max(med, 1.0)) & (miss > 25)) [0] if method != "sgp4-spread" else np.where(Ds[:, k] > 3 * np.nanmedian(Ds[:, k]))[0]
    used = np.setdiff1d(all_idx, bad)
    if len(bad) and len(used) >= min_fragments:
        sol.flags.append("OUTLIERS")
        for i in bad:
            sol.excluded[int(frags.loc[i, "norad_cat_id"])] = "orbit misses the breakup point by > 3x the median"
        with np.errstate(all="ignore"):
            est = estimate(used)
    else:
        used = all_idx
    k_s, k = est
    sol.used_norads = [int(x) for x in frags.loc[used, "norad_cat_id"]]
    sol.n_used = int(len(used))

    # refine the chosen minimum to ~1 s on the objective that defined it
    obj = spread_obj if method == "sgp4-spread" else cross_obj
    t0 = grid[k]

    def f(dt: float) -> float:
        with np.errstate(all="ignore"):
            return float(np.nanmedian(obj(pd.DatetimeIndex([t0 + pd.Timedelta(seconds=dt)]))[used, 0]))

    res = minimize_scalar(f, bounds=(-3 * step_s, 3 * step_s), method="bounded", options={"xatol": 0.5})
    t_best = t0 + pd.Timedelta(seconds=float(res.x))
    at = pd.DatetimeIndex([t_best])
    with np.errstate(all="ignore"):
        spread_at = float(np.nanmedian(spread_obj(at)[used, 0]))
        cross_at = float(np.nanmedian(cross_obj(at)[used, 0]))
    sol.spread_km = spread_at if method == "sgp4-spread" else cross_at
    sol.t_p50 = t_best

    # bootstrap over fragments
    rng = np.random.default_rng(seed)
    picks = []
    for _ in range(n_boot):
        idx = used[rng.integers(0, len(used), len(used))]
        with np.errstate(all="ignore"):
            e = estimate(idx)
        if e is not None:
            picks.append(grid[e[1]].value)
    if picks and len(used) > 1:
        sol.t_p05 = pd.Timestamp(int(np.percentile(picks, 5)), tz="UTC")
        sol.t_p95 = pd.Timestamp(int(np.percentile(picks, 95)), tz="UTC")
        # make sure the interval contains the refined point estimate
        sol.t_p05 = min(sol.t_p05, t_best)
        sol.t_p95 = max(sol.t_p95, t_best)
        if (sol.t_p95 - sol.t_p05).total_seconds() > 1.5 * period_s:
            sol.flags.append("MULTIMODAL")

    # location from the parent state at t*
    p = propagate(parent.to_frame().T, [t_best])
    r, v = p.r[0, 0], p.v[0, 0]
    if np.all(np.isfinite(r)):
        jd, fr = to_jd([t_best])
        lat, lon, alt = teme_to_geodetic(r[None, :], jd + fr)
        sol.lat, sol.lon, sol.alt_km = float(lat[0]), float(lon[0]), float(alt[0])
        sol.arg_lat_deg = argument_of_latitude_deg(r, v)

    # flags
    if spread_at > low_conf_km:
        sol.flags.append("LOW_CONFIDENCE")
    lag = (pd.to_datetime(frags.loc[used, "epoch"]) - t_best).dt.total_seconds().median() / 86400
    if lag > 7:
        sol.flags.append("LONG_BACKPROP")
    if abs((pd.Timestamp(parent["epoch"]) - t_best).total_seconds()) / 86400 > 7:
        sol.flags.append("STALE_PARENT")

    # curves for plotting (≤ ~800 points each)
    with np.errstate(all="ignore"):
        cs = np.nanmedian(Ds[used], axis=0)
        cc = np.nanmedian(Dc[used], axis=0)
    stride = max(1, len(grid) // 360)
    sol.curve = [
        {"t": grid[i].isoformat(timespec="seconds"), "spread_km": _r(cs[i], 1), "cross_km": _r(cc[i], 2)}
        for i in range(0, len(grid), stride)
    ]
    mins = _local_minima(cc, order)
    sol.crossings = [{"t": grid[i].isoformat(timespec="seconds"), "km": _r(cc[i], 2)} for i in mins]
    if references:
        for label, t in references:
            if len(mins) == 0:
                continue
            j = mins[np.argmin(np.abs(grid[mins] - pd.Timestamp(t)))]
            sol.sensitivity.append(
                {
                    "label": f"nearest crossing pass to {label}",
                    "t": grid[j].isoformat(),
                    "spread_km": _r(cc[j], 3),
                    "delta_min": round((pd.Timestamp(t) - grid[j]).total_seconds() / 60, 2),
                }
            )

    # sensitivity: re-solve with each fragment's second element set
    if second_sets is not None and len(second_sets) >= min_fragments:
        alt = solve(parent, second_sets, ref_time, method, window_days_before, step_s, n_boot=0,
                    low_conf_km=low_conf_km, min_fragments=min_fragments)
        sol.sensitivity.append(
            {"label": "second element sets", "t": None if alt.t_p50 is None else alt.t_p50.isoformat(),
             "spread_km": alt.spread_km}
        )
    return sol


def _make_objective(parent: pd.Series, frags: pd.DataFrame, method: str):
    psat = satrec_from_row(parent.to_dict())
    fsats = [satrec_from_row(r) for r in frags.to_dict("records")]
    from sgp4.api import SatrecArray

    farr = SatrecArray(fsats)

    def obj(times: pd.DatetimeIndex) -> np.ndarray:
        jd, fr = to_jd(times)
        ep, rp, vp = psat.sgp4_array(jd, fr)
        rp = np.where(ep[:, None] == 0, rp, np.nan)
        e, r, v = farr.sgp4(jd, fr)
        r = np.where(e[..., None] == 0, r, np.nan)
        v = np.where(e[..., None] == 0, v, np.nan)
        if method == "sgp4-spread":
            return np.linalg.norm(r - rp[None, :, :], axis=-1)
        if method == "orbit-crossing":
            return _point_to_orbit_km(rp[None, :, :], r, v)
        if method == "cloud-spread":  # parent-free: distance of each fragment to the cloud median
            c = np.nanmedian(r, axis=0, keepdims=True)
            return np.linalg.norm(r - c, axis=-1)
        raise ValueError(method)

    return obj
