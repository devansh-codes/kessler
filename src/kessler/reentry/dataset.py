"""Reentry training set without Space-Track (plan §7.6).

Each row is one element set of an object that later decayed, labelled with
``days_to_decay = DECAY_DATE (noon UTC) - EPOCH``. SATCAT decay dates are day precision, so labels carry
about ±12 h of noise. Rows come from every GP source we archive: last-GP and first-GP backfill batches,
event snapshots and the 6-hourly DECAYING group, which become labelled once the objects reenter.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from kessler.orbits.elements import apogee_alt_km, perigee_alt_km

MAX_DAYS = 120.0
TYPES = ("DEB", "R/B", "UNK")
FEATURES = [
    "perigee_km",
    "apogee_km",
    "mean_motion",
    "mean_motion_dot",
    "bstar",
    "log_baseline_days",
    "rcs",
    "f107_81",
    "ap",
    "kp_max_3d",
    "type_deb",
    "type_rb",
]


def space_weather_daily(sw: pd.DataFrame) -> pd.DataFrame:
    if sw.empty:
        return pd.DataFrame(columns=["date", "f107_81", "ap", "kp_max_3d"])
    d = sw.copy()
    d["date"] = pd.to_datetime(d["date"], utc=True)
    d = d.sort_values("date")
    d["kp_max_3d"] = d["kp_max"].rolling(3, min_periods=1).max()
    d = d.rename(columns={"f107_obs_center81": "f107_81", "ap_avg": "ap"})
    # centred 81-day mean is not known for the last ~40 days: fall back to the trailing mean
    d["f107_81"] = d["f107_81"].fillna(d.get("f107_obs_last81"))
    return d[["date", "f107_81", "ap", "kp_max_3d"]]


def featurize(gp: pd.DataFrame, satcat: pd.DataFrame, sw_daily: pd.DataFrame) -> pd.DataFrame:
    from kessler.reentry.baseline import baseline_days

    df = gp.copy()
    df["perigee_km"] = perigee_alt_km(df["mean_motion"], df["eccentricity"])
    df["apogee_km"] = apogee_alt_km(df["mean_motion"], df["eccentricity"])
    df["baseline_days"] = baseline_days(df["mean_motion"], df["mean_motion_dot"])
    df["log_baseline_days"] = np.log(df["baseline_days"])
    sc = satcat[["norad_cat_id", "object_type", "rcs", "decay_date", "object_name"]].rename(columns={"object_name": "satcat_name"})
    df = df.merge(sc, on="norad_cat_id", how="left")
    df["type_deb"] = (df["object_type"] == "DEB").astype(float)
    df["type_rb"] = (df["object_type"] == "R/B").astype(float)
    df["epoch_day"] = pd.to_datetime(df["epoch"], utc=True).dt.floor("D")
    if len(sw_daily):
        df = pd.merge_asof(
            df.sort_values("epoch_day"),
            sw_daily.rename(columns={"date": "epoch_day"}).sort_values("epoch_day"),
            on="epoch_day",
            direction="backward",
        )
    else:
        for c in ("f107_81", "ap", "kp_max_3d"):
            df[c] = np.nan
    return df


def training_set(gp: pd.DataFrame, satcat: pd.DataFrame, sw: pd.DataFrame) -> pd.DataFrame:
    sc = satcat[satcat["decay_date"].notna() & satcat["object_type"].isin(TYPES)]
    g = gp[gp["norad_cat_id"].isin(sc["norad_cat_id"])]
    if g.empty:
        return pd.DataFrame()
    df = featurize(g, sc, space_weather_daily(sw))
    decay = pd.to_datetime(df["decay_date"], errors="coerce", utc=True) + pd.Timedelta(hours=12)
    df["decay_ts"] = decay
    df["days_to_decay"] = (decay - pd.to_datetime(df["epoch"], utc=True)).dt.total_seconds() / 86400
    df = df[(df["days_to_decay"] > 0.05) & (df["days_to_decay"] <= MAX_DAYS)]
    # drop obviously invalid element sets (sub-orbital / hyperbolic)
    df = df[(df["perigee_km"] > 60) & (df["eccentricity"] < 0.5)]
    return df.sort_values("epoch").reset_index(drop=True)
