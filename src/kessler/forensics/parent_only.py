"""Parent-only mode (plan §7.5): when no fragments are public, look for the event in the parent's own
element history (changepoints in mean motion / eccentricity / B*)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from kessler.orbits.elements import mean_motion_rad_s, semi_major_axis_km


def analyse(series: pd.DataFrame, ref_time: pd.Timestamp) -> dict:
    s = series.sort_values("epoch").drop_duplicates("epoch")
    s = s[["epoch", "mean_motion", "eccentricity", "bstar"]].copy()
    s["a_km"] = semi_major_axis_km(s["mean_motion"])
    out = {
        "n_elsets": int(len(s)),
        "window_start": None,
        "window_end": None,
        "dv_t_ms": None,
        "series": [
            {
                "epoch": pd.Timestamp(r.epoch).isoformat(),
                "mean_motion": float(r.mean_motion),
                "eccentricity": float(r.eccentricity),
                "bstar": float(r.bstar),
                "a_km": float(r.a_km),
            }
            for r in s.itertuples()
        ],
        "changepoints": [],
        "note": "",
        "flags": [],
    }
    ref_time = pd.Timestamp(ref_time)
    before = s[s["epoch"] < ref_time]
    after = s[s["epoch"] >= ref_time]
    if len(before):
        out["window_start"] = pd.Timestamp(before["epoch"].iloc[-1]).isoformat()
    if len(after):
        out["window_end"] = pd.Timestamp(after["epoch"].iloc[0]).isoformat()

    gap_ok = len(before) and len(after) and (after["epoch"].iloc[0] - before["epoch"].iloc[-1]) <= pd.Timedelta(days=60)
    if len(before) and len(after) and not gap_ok:
        out["note"] = (
            f"The nearest element sets before and after the event are "
            f"{(after['epoch'].iloc[0] - before['epoch'].iloc[-1]).days} days apart, too far to isolate the event."
        )
    if gap_ok:
        b, a = before.iloc[-1], after.iloc[0]
        a0, a1 = float(b["a_km"]), float(a["a_km"])
        n = float(mean_motion_rad_s((b["mean_motion"] + a["mean_motion"]) / 2))
        aa = (a0 + a1) / 2
        out["dv_t_ms"] = float(n * aa / 2 * (a1 - a0) / aa * 1000)
        gap_days = (a["epoch"] - b["epoch"]).total_seconds() / 86400
        if gap_days > 3:
            out["note"] = (
                f"The bracketing element sets are {gap_days:.0f} days apart, so the implied along-track Δv "
                "also contains drag decay over that interval."
            )

    if len(s) >= 6:
        try:
            import ruptures as rpt

            X = s[["mean_motion", "eccentricity", "bstar"]].to_numpy(dtype=float)
            X = (X - X.mean(0)) / np.where(X.std(0) > 0, X.std(0), 1)
            algo = rpt.Pelt(model="l2", min_size=2).fit(X)
            bkps = algo.predict(pen=3 * np.log(len(X)))
            for k in bkps[:-1]:
                out["changepoints"].append({"field": "mn/ecc/bstar", "epoch": pd.Timestamp(s["epoch"].iloc[k]).isoformat()})
        except Exception as e:  # pragma: no cover - ruptures edge cases on tiny inputs
            out["note"] += f" Changepoint search failed: {e}."
    else:
        out["flags"].append("INSUFFICIENT_HISTORY")
        out["note"] = (
            out["note"]
            + f" Only {len(s)} element set(s) are available for the parent. Changepoint detection needs at "
            "least 6; history accumulates with every 6-hourly ingest."
        ).strip()
    return out
