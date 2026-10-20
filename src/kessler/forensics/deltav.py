"""Δv per fragment in the parent's RTN frame at the breakup (plan §7.3).

Each fragment's state is taken at the point of *its own orbit* closest to the breakup point (searched
within ±half an orbit of t*), not at t* itself. Along-track timing error from long back-propagation then
does not rotate the velocity vector. The miss distance is reported as ``residual_km``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from sgp4.api import SatrecArray

from kessler.orbits.frames import to_rtn
from kessler.orbits.propagate import satrec_from_row, to_jd

MAX_RESIDUAL_KM = 500.0


def fragment_dv(parent: pd.Series, frags: pd.DataFrame, t_star: pd.Timestamp) -> pd.DataFrame:
    psat = satrec_from_row(parent.to_dict())
    jd, fr = to_jd([t_star])
    e, rp, vp = psat.sgp4(jd[0], fr[0])
    if e != 0 or len(frags) == 0:
        return pd.DataFrame(columns=["norad_cat_id", "dv_r", "dv_t", "dv_n", "dv_mag", "residual_km", "dt_s"])
    rp, vp = np.array(rp), np.array(vp)
    period_s = 2 * np.pi / psat.no_kozai * 60
    offsets = np.arange(-period_s / 2, period_s / 2, 5.0)
    times = pd.DatetimeIndex([t_star + pd.Timedelta(seconds=float(s)) for s in offsets])
    jds, frs = to_jd(times)
    arr = SatrecArray([satrec_from_row(r) for r in frags.to_dict("records")])
    ee, R, V = arr.sgp4(jds, frs)
    d = np.linalg.norm(R - rp[None, None, :], axis=-1)
    d = np.where(ee == 0, d, np.inf)
    k = np.argmin(d, axis=1)
    idx = np.arange(len(frags))
    v_i, miss = V[idx, k], d[idx, k]
    dv = (v_i - vp[None, :]) * 1000.0  # m/s
    rtn = to_rtn(dv, np.repeat(rp[None, :], len(frags), 0), np.repeat(vp[None, :], len(frags), 0))
    out = pd.DataFrame(
        {
            "norad_cat_id": frags["norad_cat_id"].astype("int64").to_numpy(),
            "dv_r": rtn[:, 0],
            "dv_t": rtn[:, 1],
            "dv_n": rtn[:, 2],
            "dv_mag": np.linalg.norm(dv, axis=1),
            "residual_km": miss,
            "dt_s": offsets[k],
        }
    )
    out = out[np.isfinite(out["dv_mag"])].reset_index(drop=True)
    # a fragment whose orbit never comes near the breakup point (SGP4 failure, decayed in
    # back-propagation) gives a meaningless Δv: keep the row but mark it unreliable
    out["reliable"] = np.isfinite(out["residual_km"]) & (out["residual_km"] <= MAX_RESIDUAL_KM)
    return out


def dv_stats(dv: pd.DataFrame) -> dict | None:
    m = dv["dv_mag"].to_numpy()
    m = m[np.isfinite(m) & (m > 0)]
    if len(m) == 0:
        return None
    if len(m) >= 3:
        sigma, _, scale = stats.lognorm.fit(m, floc=0)
        mu = float(np.log(scale))
    else:
        mu, sigma = float(np.mean(np.log(m))), float(np.std(np.log(m)))
    return {
        "n": int(len(m)),
        "median_ms": float(np.median(m)),
        "p90_ms": float(np.percentile(m, 90)),
        "max_ms": float(np.max(m)),
        "lognorm_mu": mu,
        "lognorm_sigma": float(sigma),
    }
