"""NOAA SWPC live planetary Kp and F10.7 (public domain). Used for the live space-weather strip."""

from __future__ import annotations

import json

import pandas as pd

from kessler.http import PoliteClient

KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
F107_URL = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"


def parse_kp(text: str) -> pd.DataFrame:
    data = json.loads(text)
    if data and isinstance(data[0], list):  # legacy: header row + rows
        header, rows = data[0], data[1:]
        data = [dict(zip(header, r, strict=False)) for r in rows]
    df = pd.DataFrame(data)
    kp_col = "Kp" if "Kp" in df.columns else "kp_index" if "kp_index" in df.columns else None
    if kp_col is None or "time_tag" not in df.columns:
        raise ValueError(f"unexpected SWPC Kp columns: {list(df.columns)}")
    out = pd.DataFrame(
        {
            "time_tag": pd.to_datetime(df["time_tag"], utc=True),
            "kp": pd.to_numeric(df[kp_col], errors="coerce").astype("float64"),
        }
    )
    return out.dropna()


def parse_f107(text: str) -> pd.DataFrame:
    df = pd.DataFrame(json.loads(text))
    if "time_tag" not in df.columns or "flux" not in df.columns:
        raise ValueError(f"unexpected SWPC F10.7 columns: {list(df.columns)}")
    out = pd.DataFrame(
        {
            "time_tag": pd.to_datetime(df["time_tag"], utc=True),
            "flux": pd.to_numeric(df["flux"], errors="coerce").astype("float64"),
        }
    )
    return out.dropna().drop_duplicates("time_tag", keep="last")


def fetch(client: PoliteClient, ttl_s: int | None = None):
    k = client.get(KP_URL, ttl_s=ttl_s)
    kp = parse_kp(k.text)
    kp["fetched_at"] = pd.Timestamp(k.fetched_at)
    f = client.get(F107_URL, ttl_s=ttl_s)
    f107 = parse_f107(f.text)
    f107["fetched_at"] = pd.Timestamp(f.fetched_at)
    return kp, f107
