"""CelesTrak GP (OMM) queries. CSV only: TLE cannot represent NORAD IDs above 99999."""

from __future__ import annotations

import io
from datetime import datetime
from urllib.parse import quote

import pandas as pd

from kessler.http import Fetched, PoliteClient
from kessler.warehouse.schema import OMM_COLUMNS

BASE = "https://celestrak.org/NORAD/elements"
ENDPOINTS = {"current": "gp.php", "first": "gp-first.php", "last": "gp-last.php"}
QUERY_KEYS = {"CATNR", "INTDES", "GROUP", "NAME", "SPECIAL"}
EMPTY_MARKER = "No GP data found"


class SchemaError(ValueError):
    pass


def gp_url(key: str, value: str | int, kind: str = "current") -> str:
    key = key.upper()
    if key not in QUERY_KEYS:
        raise ValueError(f"unknown GP query key {key}")
    return f"{BASE}/{ENDPOINTS[kind]}?{key}={quote(str(value))}&FORMAT=CSV"


def is_empty(text: str) -> bool:
    return text.strip() == "" or text.strip().startswith(EMPTY_MARKER)


def parse_gp_csv(text: str) -> pd.DataFrame:
    """Parse OMM CSV into the warehouse column layout (lower-case names, typed)."""
    if is_empty(text):
        return pd.DataFrame(columns=[c.lower() for c in OMM_COLUMNS])
    df = pd.read_csv(io.StringIO(text), dtype={"OBJECT_ID": "string", "OBJECT_NAME": "string"})
    missing = set(OMM_COLUMNS) - set(df.columns)
    if missing:
        raise SchemaError(f"OMM CSV missing columns: {sorted(missing)}")
    df = df[OMM_COLUMNS].copy()
    df.columns = [c.lower() for c in df.columns]
    df["norad_cat_id"] = df["norad_cat_id"].astype("int64")
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True, format="ISO8601")
    for c in ("element_set_no", "rev_at_epoch", "ephemeris_type"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    for c in (
        "mean_motion",
        "eccentricity",
        "inclination",
        "ra_of_asc_node",
        "arg_of_pericenter",
        "mean_anomaly",
        "bstar",
        "mean_motion_dot",
        "mean_motion_ddot",
    ):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    df["object_name"] = df["object_name"].astype("string")
    df["object_id"] = df["object_id"].astype("string")
    df["classification_type"] = df["classification_type"].astype("string")
    return df


def annotate(df: pd.DataFrame, fetched: Fetched, source_query: str, kind: str) -> pd.DataFrame:
    df = df.copy()
    df["fetched_at"] = pd.Timestamp(fetched.fetched_at)
    df["source_query"] = source_query
    df["is_first_gp"] = kind == "first"
    df["is_last_gp"] = kind == "last"
    return df


def fetch(client: PoliteClient, key: str, value: str | int, kind: str = "current", ttl_s: int | None = None):
    url = gp_url(key, value, kind)
    f = client.get(url, ttl_s=ttl_s)
    df = parse_gp_csv(f.text)
    return annotate(df, f, f"{kind}:{key.upper()}={value}", kind), f


def epoch_to_datetime(epoch) -> datetime:
    return pd.Timestamp(epoch).to_pydatetime()
