"""GCAT (Jonathan McDowell, CC-BY 4.0): object catalog (+100k file) and launch list. Weekly refresh."""

from __future__ import annotations

import io
import re

import pandas as pd

from kessler.http import PoliteClient

BASE = "https://planet4589.org/space/gcat"
SATCAT_TSV = f"{BASE}/tsv/cat/satcat.tsv"
SATCAT100K_TSV = f"{BASE}/tsv/cat/satcat100k.tsv"
LAUNCH_TSV = f"{BASE}/tsv/launch/launch.tsv"
WEEK_S = 7 * 86400

OBJECT_KEEP = {
    "JCAT": "jcat",
    "Satcat": "satcat",
    "Launch_Tag": "launch_tag",
    "Piece": "piece",
    "Type": "type",
    "Name": "name",
    "LDate": "ldate",
    "Parent": "parent",
    "SDate": "sdate",
    "DDate": "ddate",
    "Status": "status",
    "Owner": "owner",
    "State": "state",
    "Perigee": "perigee",
    "Apogee": "apogee",
    "Inc": "inc",
    "OpOrbit": "op_orbit",
}
LAUNCH_KEEP = {
    "Launch_Tag": "launch_tag",
    "Launch_Date": "launch_date",
    "LV_Type": "lv_type",
    "Variant": "variant",
    "Flight_ID": "flight_id",
    "Mission": "mission",
    "Launch_Site": "launch_site",
    "Agency": "agency",
    "LaunchCode": "launch_code",
    "Category": "category",
}


def _read_tsv(text: str) -> tuple[pd.DataFrame, str | None]:
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#"):
        raise ValueError("GCAT TSV must start with a '#' header line")
    header = lines[0].lstrip("#").split("\t")
    updated = None
    body = []
    for ln in lines[1:]:
        if ln.startswith("#"):
            m = re.search(r"Updated\s+(.*)", ln)
            if m:
                updated = m.group(1).strip()
            continue
        body.append(ln)
    df = pd.read_csv(
        io.StringIO("\n".join(body)), sep="\t", names=header, dtype="string", keep_default_na=False, quoting=3
    )
    df = df.apply(lambda s: s.str.strip())
    return df, updated


def gcat_date(s: pd.Series) -> pd.Series:
    """GCAT dates look like '1957 Oct  4 1933?' -> UTC timestamp at day precision."""
    cleaned = s.fillna("").str.replace("?", "", regex=False).str.extract(r"^(\d{4} \w{3}\s+\d{1,2})")[0]
    return pd.to_datetime(cleaned.str.replace(r"\s+", " ", regex=True), format="%Y %b %d", errors="coerce", utc=True)


def parse_objects(text: str) -> tuple[pd.DataFrame, str | None]:
    df, updated = _read_tsv(text)
    missing = set(OBJECT_KEEP) - set(df.columns)
    if missing:
        raise ValueError(f"GCAT satcat missing columns {sorted(missing)}")
    df = df[list(OBJECT_KEEP)].rename(columns=OBJECT_KEEP)
    df["satcat_num"] = pd.to_numeric(df["satcat"], errors="coerce").astype("Int64")
    df["type_class"] = df["type"].str[:1]
    for c in ("perigee", "apogee", "inc"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    df["ldate_ts"] = gcat_date(df["ldate"])
    df["ddate_ts"] = gcat_date(df["ddate"])
    return df, updated


def parse_launches(text: str) -> tuple[pd.DataFrame, str | None]:
    df, updated = _read_tsv(text)
    missing = set(LAUNCH_KEEP) - set(df.columns)
    if missing:
        raise ValueError(f"GCAT launch list missing columns {sorted(missing)}")
    df = df[list(LAUNCH_KEEP)].rename(columns=LAUNCH_KEEP)
    df["launch_ts"] = gcat_date(df["launch_date"])
    return df.drop_duplicates("launch_tag", keep="first"), updated


def fetch(client: PoliteClient):
    """Returns (objects, launches, release_string). Each file is cached for a week."""
    a = client.get(SATCAT_TSV, ttl_s=WEEK_S)
    b = client.get(SATCAT100K_TSV, ttl_s=WEEK_S)
    c = client.get(LAUNCH_TSV, ttl_s=WEEK_S)
    oa, upd = parse_objects(a.text)
    ob, _ = parse_objects(b.text)
    objects = pd.concat([oa, ob], ignore_index=True).drop_duplicates("jcat", keep="last")
    launches, _ = parse_launches(c.text)
    release = f"GCAT (updated {upd})" if upd else "GCAT"
    objects["gcat_release"] = release
    launches["gcat_release"] = release
    return objects, launches, release
