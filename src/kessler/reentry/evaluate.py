"""Time-ordered backtest: train (oldest 60%) → conformal calibration (next 20%) → test (newest 20%).

Leakage guard: a row may only be used for fitting if its object had *already decayed* before the start
of the block it is evaluated against; otherwise the label would come from the future.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from kessler.reentry.model import LEVELS, QuantileModel

LEAD_BINS = [0, 1, 3, 7, 14, 30, 60, 120]


def _mae(pred: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    err = np.abs(pred - y)
    return float(np.mean(err)), float(np.mean(err / y) * 100)


def lead_time_days(df: pd.DataFrame, inside: np.ndarray) -> float | None:
    """Median over objects of the earliest days-before-decay from which the 80% interval keeps covering."""
    d = df.assign(inside=inside)
    leads = []
    for _, g in d.groupby("norad_cat_id"):
        g = g.sort_values("days_to_decay")  # closest to decay first
        lead = 0.0
        for r in g.itertuples():
            if not r.inside:
                break
            lead = r.days_to_decay
        if len(g) >= 2:
            leads.append(lead)
    return float(np.median(leads)) if leads else None


def backtest(df: pd.DataFrame, seed: int = 0) -> tuple[dict, QuantileModel | None]:
    df = df.sort_values("epoch").reset_index(drop=True)
    n = len(df)
    notes: list[str] = []
    if n < 200:
        return {"n_train": int(n), "n_holdout": 0, "metrics": [], "calibration": [], "lead_time": [], "notes": [f"Only {n} labelled element sets so far; need at least 200 for a backtest. The set grows with every ingest run."]}, None
    i_cal, i_test = int(n * 0.6), int(n * 0.8)
    t_cal, t_test = df["epoch"].iloc[i_cal], df["epoch"].iloc[i_test]
    train = df.iloc[:i_cal]
    train = train[train["decay_ts"] < t_cal]
    cal = df.iloc[i_cal:i_test]
    cal = cal[cal["decay_ts"] < t_test]
    test = df.iloc[i_test:]
    model = QuantileModel().fit(train, train["days_to_decay"].to_numpy(), seed)
    model.calibrate(cal, cal["days_to_decay"].to_numpy())
    y = test["days_to_decay"].to_numpy()
    p50 = model.median(test)
    base = test["baseline_days"].to_numpy()
    lo80, hi80 = model.interval(test, 0.8)
    raw_lo, raw_hi = model.interval(test, 0.8, conformal=False)
    inside = (y >= lo80) & (y <= hi80)
    mae_m, pct_m = _mae(p50, y)
    mae_b, pct_b = _mae(base, y)
    # baseline "interval": ±50% around the point estimate, for an equal-footing coverage number
    b_inside = (y >= base * 0.5) & (y <= base * 1.5)
    metrics = [
        {"model": "Quantile GBM + conformal", "mae_days": mae_m, "mae_pct": pct_m, "coverage80": float(inside.mean()), "median_lead_days": lead_time_days(test, inside), "skill_vs_baseline": 1 - mae_m / mae_b},
        {"model": "Quantile GBM (raw)", "mae_days": mae_m, "mae_pct": pct_m, "coverage80": float(((y >= raw_lo) & (y <= raw_hi)).mean()), "median_lead_days": lead_time_days(test, (y >= raw_lo) & (y <= raw_hi)), "skill_vs_baseline": 1 - mae_m / mae_b},
        {"model": "Physics baseline", "mae_days": mae_b, "mae_pct": pct_b, "coverage80": float(b_inside.mean()), "median_lead_days": lead_time_days(test, b_inside), "skill_vs_baseline": 0.0},
    ]
    calibration = []
    for level in LEVELS:
        for conf, name in ((True, "conformal"), (False, "raw")):
            lo, hi = model.interval(test, level, conformal=conf)
            calibration.append({"nominal": level, "empirical": float(((y >= lo) & (y <= hi)).mean()), "model": name})
    lead = []
    for a, b in zip(LEAD_BINS[:-1], LEAD_BINS[1:], strict=False):
        m = (y > a) & (y <= b)
        if m.sum() >= 5:
            lead.append({"days_before": b, "coverage": float(inside[m].mean()), "model": "conformal", "n": int(m.sum()), "mae_days": float(np.mean(np.abs(p50[m] - y[m]))), "baseline_mae_days": float(np.mean(np.abs(base[m] - y[m])))})
    cov = float(inside.mean())
    if abs(cov - 0.8) > 0.05:
        notes.append(
            f"Holdout 80% coverage is {cov:.0%}. The newest block can differ from the calibration block "
            "(different solar activity, object mix and backfill order), and conformal guarantees assume exchangeability."
        )
    notes.append("Labels are SATCAT decay dates (day precision, ±12 h).")
    importance = []
    return {
        "n_train": int(len(train)),
        "n_calibration": int(len(cal)),
        "n_holdout": int(len(test)),
        "holdout_start": pd.Timestamp(t_test).isoformat(),
        "metrics": metrics,
        "calibration": calibration,
        "lead_time": lead,
        "notes": notes,
        "feature_importance": importance,
        "objects": int(df["norad_cat_id"].nunique()),
    }, model
