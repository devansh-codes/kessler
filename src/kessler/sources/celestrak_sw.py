"""CelesTrak space weather (SW-All.csv once for backfill, SW-Last5Years.csv at most daily)."""

from __future__ import annotations

import io

import pandas as pd

from kessler.http import Fetched, PoliteClient

SW_ALL = "https://celestrak.org/SpaceData/SW-All.csv"
SW_LAST5 = "https://celestrak.org/SpaceData/SW-Last5Years.csv"

COLUMN_MAP = {
    "DATE": "date",
    "KP_SUM": "kp_sum",
    "AP_AVG": "ap_avg",
    "F10.7_OBS": "f107_obs",
    "F10.7_ADJ": "f107_adj",
    "F10.7_DATA_TYPE": "f107_data_type",
    "F10.7_OBS_CENTER81": "f107_obs_center81",
    "F10.7_OBS_LAST81": "f107_obs_last81",
    "F10.7_ADJ_CENTER81": "f107_adj_center81",
    "F10.7_ADJ_LAST81": "f107_adj_last81",
}
KP_COLS = [f"KP{i}" for i in range(1, 9)]


def parse_sw_csv(text: str) -> pd.DataFrame:
    raw = pd.read_csv(io.StringIO(text))
    missing = (set(COLUMN_MAP) | set(KP_COLS)) - set(raw.columns)
    if missing:
        raise ValueError(f"space weather CSV missing columns: {sorted(missing)}")
    df = raw[list(COLUMN_MAP)].rename(columns=COLUMN_MAP)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    # KPn are stored x10 in the CelesTrak file (e.g. 33 == Kp 3.3); keep the daily max in Kp units
    df["kp_max"] = raw[KP_COLS].max(axis=1) / 10.0
    for c in df.columns:
        if c not in ("date", "f107_data_type"):
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    df["kp_sum"] = df["kp_sum"] / 10.0  # also stored x10
    df["f107_data_type"] = df["f107_data_type"].astype("string")
    return df


def fetch(client: PoliteClient, full: bool, ttl_s: int | None = None) -> tuple[pd.DataFrame, Fetched]:
    f = client.get(SW_ALL if full else SW_LAST5, ttl_s=ttl_s)
    df = parse_sw_csv(f.text)
    df["fetched_at"] = pd.Timestamp(f.fetched_at)
    df["source"] = "celestrak:" + ("SW-All" if full else "SW-Last5Years")
    return df, f
