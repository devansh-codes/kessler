"""Precomputed ephemerides for the globe (plan §8.4): Float32 LE [T][N][3] = (lat, lon, alt_km).

Two regimes, labelled in the metadata:

* **dense** (default 12 h at 120 s after t*): the cloud is *reconstructed*. Every fragment starts at the
  parent's position at t* with the parent velocity plus its fitted Δv, then is propagated with two-body
  + J2 (RK4). This shows what the analysis implies: a cloud spreading from a point.
* **daily** (default 60 days): SGP4 from each object's catalogued element set nearest in time.

Objects are NaN (hidden) after their SATCAT decay date and wherever SGP4 fails.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from kessler.orbits.frames import teme_to_geodetic
from kessler.orbits.propagate import satrec_from_row, to_jd

MU = 398600.4418
J2 = 1.08262668e-3
RE = 6378.137


def _accel(r: np.ndarray) -> np.ndarray:
    x, y, z = r[..., 0], r[..., 1], r[..., 2]
    r2 = np.sum(r * r, axis=-1)
    rn = np.sqrt(r2)
    k = -MU / (rn**3)
    f = 1.5 * J2 * MU * RE**2 / (rn**5)
    zz = 5 * z * z / r2
    ax = k * x + f * x * (zz - 1)
    ay = k * y + f * y * (zz - 1)
    az = k * z + f * z * (zz - 3)
    return np.stack([ax, ay, az], axis=-1)


def rk4_j2(r0: np.ndarray, v0: np.ndarray, t_out: np.ndarray, h: float = 10.0) -> np.ndarray:
    """Propagate states (N,3) with two-body + J2; returns positions (N, len(t_out), 3)."""
    r, v = r0.astype(float).copy(), v0.astype(float).copy()
    out = np.empty((r.shape[0], len(t_out), 3))
    t = 0.0
    for j, T in enumerate(t_out):
        while t < T - 1e-9:
            dt = min(h, T - t)
            k1v = _accel(r)
            k1r = v
            k2v = _accel(r + 0.5 * dt * k1r)
            k2r = v + 0.5 * dt * k1v
            k3v = _accel(r + 0.5 * dt * k2r)
            k3r = v + 0.5 * dt * k2v
            k4v = _accel(r + dt * k3r)
            k4r = v + dt * k3v
            r = r + dt / 6 * (k1r + 2 * k2r + 2 * k3r + k4r)
            v = v + dt / 6 * (k1v + 2 * k2v + 2 * k3v + k4v)
            t += dt
        out[:, j] = r
    return out


def build_ephemeris(
    t_star: pd.Timestamp,
    objects: pd.DataFrame,
    gp: pd.DataFrame,
    parent_norad: int,
    dv: pd.DataFrame | None,
    decay: dict[int, pd.Timestamp],
    dense_hours: float = 12,
    dense_step_s: float = 120,
    daily_days: int = 60,
    now: pd.Timestamp | None = None,
) -> tuple[np.ndarray, dict]:
    """``objects``: rows with norad_cat_id, name (parent first)."""
    t_star = pd.Timestamp(t_star)
    norads = objects["norad_cat_id"].astype("int64").tolist()
    names = objects["name"].astype(str).tolist()
    N = len(norads)
    dense = np.arange(0, dense_hours * 3600 + 1, dense_step_s, dtype=float)
    daily = np.arange(1, daily_days + 1, dtype=float) * 86400.0
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    daily = daily[(t_star + pd.to_timedelta(daily, unit="s")) <= now + pd.Timedelta(days=1)]
    times = np.concatenate([dense, daily])
    T = len(times)
    lla = np.full((T, N, 3), np.nan, dtype=np.float64)
    abs_times = pd.DatetimeIndex([t_star + pd.Timedelta(seconds=float(s)) for s in times])
    jd, fr = to_jd(abs_times)

    # ---- parent via SGP4 (element set nearest each time) ----------------------------------
    def sgp4_track(norad: int, which: np.ndarray) -> np.ndarray:
        g = gp[gp["norad_cat_id"] == norad].sort_values("epoch")
        res = np.full((len(which), 3), np.nan)
        if g.empty:
            return res
        sats = [satrec_from_row(r) for r in g.to_dict("records")]
        ep = g["epoch"].astype("int64").to_numpy()
        for j, ti in enumerate(which):
            k = int(np.argmin(np.abs(ep - abs_times[ti].value)))
            e, r, _ = sats[k].sgp4(jd[ti], fr[ti])
            if e == 0:
                res[j] = r
        return res

    all_idx = np.arange(T)
    p_teme = sgp4_track(parent_norad, all_idx)

    # ---- dense: reconstructed cloud from Δv --------------------------------------------------
    nd = len(dense)
    psat_rows = gp[gp["norad_cat_id"] == parent_norad].sort_values("epoch")
    recon = 0
    if dv is not None and len(dv) and not psat_rows.empty:
        k = int(np.argmin(np.abs(psat_rows["epoch"].astype("int64").to_numpy() - t_star.value)))
        ps = satrec_from_row(psat_rows.iloc[k].to_dict())
        j0, f0 = to_jd([t_star])
        e, rp, vp = ps.sgp4(j0[0], f0[0])
        if e == 0:
            rp, vp = np.array(rp), np.array(vp)
            dvm = dv.set_index("norad_cat_id")
            frag_ix = [i for i, n in enumerate(norads) if n != parent_norad and n in dvm.index]
            if frag_ix:
                from kessler.orbits.frames import rtn_basis

                B = rtn_basis(rp, vp)  # rows R,T,N
                dv_rtn = np.array([[dvm.loc[norads[i], c] for c in ("dv_r", "dv_t", "dv_n")] for i in frag_ix]) / 1000.0
                dv_teme = dv_rtn @ B
                r0 = np.repeat(rp[None, :], len(frag_ix), 0)
                v0 = vp[None, :] + dv_teme
                pos = rk4_j2(r0, v0, dense)
                lat, lon, alt = teme_to_geodetic(pos, (jd[:nd] + fr[:nd])[None, :])
                for a, i in enumerate(frag_ix):
                    lla[:nd, i, 0], lla[:nd, i, 1], lla[:nd, i, 2] = lat[a], lon[a], alt[a]
                recon = len(frag_ix)

    # ---- daily (and dense for objects without Δv): SGP4 -----------------------------------
    for i, n in enumerate(norads):
        which = all_idx if (n == parent_norad) else (all_idx if np.all(np.isnan(lla[:nd, i, 0])) else np.arange(nd, T))
        teme = p_teme[which] if n == parent_norad else sgp4_track(n, which)
        lat, lon, alt = teme_to_geodetic(teme, (jd[which] + fr[which]))
        lla[which, i, 0], lla[which, i, 1], lla[which, i, 2] = lat, lon, alt

    # hide after decay, and hide anything below 80 km (reentered)
    decay_s: list[float | None] = []
    for i, n in enumerate(norads):
        d = decay.get(n)
        if d is not None:
            ds = (pd.Timestamp(d) + pd.Timedelta(hours=12) - t_star).total_seconds()
            decay_s.append(ds)
            lla[times > ds, i, :] = np.nan
        else:
            decay_s.append(None)
    low = lla[..., 2] < 80
    lla[low] = np.nan

    arr = lla.astype("<f4")
    meta = {
        "t0": t_star.isoformat(),
        "times": [float(t) for t in times],
        "step_s": [float(dense_step_s)] * nd + [86400.0] * (T - nd),
        "T": int(T),
        "N": int(N),
        "norads": [int(n) for n in norads],
        "names": names,
        "parent_index": int(norads.index(parent_norad)) if parent_norad in norads else 0,
        "decay_s": decay_s,
        "dense_until_s": float(dense[-1]),
        "reconstructed": int(recon),
    }
    return arr, meta
