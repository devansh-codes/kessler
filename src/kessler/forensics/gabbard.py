"""Gabbard diagram points: (period, apogee) and (period, perigee) per object per snapshot."""

from __future__ import annotations

import pandas as pd

from kessler.orbits.elements import apogee_alt_km, perigee_alt_km, period_min


def gabbard_points(gp: pd.DataFrame, norads: list[int], parent_norad: int, decay: dict[int, pd.Timestamp], max_snapshots: int = 24) -> pd.DataFrame:
    """For each snapshot date, each object's latest element set at or before that date."""
    g = gp[gp["norad_cat_id"].isin(norads)].sort_values("epoch")
    if g.empty:
        return pd.DataFrame(columns=["norad_cat_id", "epoch", "snapshot", "period", "apo", "peri", "parent"])
    days = pd.DatetimeIndex(sorted(set(g["epoch"].dt.floor("D")))) + pd.Timedelta(days=1)
    if len(days) > max_snapshots:
        idx = sorted({round(i * (len(days) - 1) / (max_snapshots - 1)) for i in range(max_snapshots)})
        days = days[idx]
    out = []
    for d in days:
        upto = g[g["epoch"] < d].groupby("norad_cat_id").tail(1)
        for r in upto.itertuples():
            dd = decay.get(int(r.norad_cat_id))
            if dd is not None and dd < d - pd.Timedelta(days=1):
                continue
            out.append(
                {
                    "norad_cat_id": int(r.norad_cat_id),
                    "epoch": r.epoch,
                    "snapshot": d,
                    "period": float(period_min(r.mean_motion)),
                    "apo": float(apogee_alt_km(r.mean_motion, r.eccentricity)),
                    "peri": float(perigee_alt_km(r.mean_motion, r.eccentricity)),
                    "parent": int(r.norad_cat_id) == parent_norad,
                }
            )
    return pd.DataFrame(out)
