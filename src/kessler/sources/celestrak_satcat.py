"""CelesTrak SATCAT: object metadata and DECAY_DATE (the reentry ground truth, day precision)."""

from __future__ import annotations

import io
from urllib.parse import quote

import pandas as pd

from kessler.http import Fetched, PoliteClient
from kessler.warehouse.schema import SATCAT_COLUMNS

RECORDS = "https://celestrak.org/satcat/records.php"
FULL_CATALOG = "https://celestrak.org/pub/satcat.csv"


def records_url(key: str, value: str | int) -> str:
    return f"{RECORDS}?{key.upper()}={quote(str(value))}&FORMAT=CSV"


def parse_satcat_csv(text: str) -> pd.DataFrame:
    if not text.strip() or not text.lstrip().startswith("OBJECT_NAME"):
        return pd.DataFrame(columns=[c.lower() for c in SATCAT_COLUMNS])
    df = pd.read_csv(io.StringIO(text), dtype="string", keep_default_na=False)
    missing = set(SATCAT_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"SATCAT CSV missing columns: {sorted(missing)}")
    df = df[SATCAT_COLUMNS].copy()
    df.columns = [c.lower() for c in df.columns]
    df = df.replace({"": pd.NA})
    df["norad_cat_id"] = df["norad_cat_id"].astype("int64")
    for c in ("period", "inclination", "apogee", "perigee", "rcs"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    for c in ("launch_date", "decay_date"):
        # keep as ISO date strings (day precision) to make the key comparison exact
        df[c] = df[c].astype("string")
    return df


def annotate(df: pd.DataFrame, fetched: Fetched, source_query: str) -> pd.DataFrame:
    df = df.copy()
    df["fetched_at"] = pd.Timestamp(fetched.fetched_at)
    df["source_query"] = source_query
    return df


def fetch(client: PoliteClient, key: str, value: str | int, ttl_s: int | None = None):
    f = client.get(records_url(key, value), ttl_s=ttl_s)
    return annotate(parse_satcat_csv(f.text), f, f"satcat:{key.upper()}={value}"), f


def fetch_full(client: PoliteClient, ttl_s: int | None = None):
    f = client.get(FULL_CATALOG, ttl_s=ttl_s)
    return annotate(parse_satcat_csv(f.text), f, "satcat:FULL"), f
