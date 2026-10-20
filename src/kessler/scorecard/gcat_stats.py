"""Rocket stage scorecard from GCAT (plan §7.7).

Joins GCAT objects (satcat + satcat100k) to the launch list on Launch_Tag, groups launch vehicles into
families, and counts per family: orbital launches, rocket stages, debris whose GCAT ``Parent`` is a
rocket stage, and stage fragmentation events (a stage with at least ``FRAG_MIN`` catalogued debris
pieces; a proxy, since GCAT's event catalog is not ingested).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

FRAG_MIN = 5
HIGHLIGHT = {"Long March 6A", "Long March 6C", "Falcon 9"}
RULES: list[tuple[str, str]] = [
    (r"^Falcon 9", "Falcon 9"),
    (r"^Falcon Heavy", "Falcon Heavy"),
    (r"^Chang Zheng (\w+)", r"Long March \1"),
    (r"^Delta 7\d{3}", "Delta II"),
    (r"^Delta \d{4}", "Thor-Delta"),
    (r"^Delta 4", "Delta IV"),
    (r"^Atlas V", "Atlas V"),
    (r"^Soyuz-2", "Soyuz-2"),
    (r"^Soyuz-U", "Soyuz-U"),
    (r"^Proton-K", "Proton-K"),
    (r"^Proton-M", "Proton-M"),
    (r"^Kosmos 11K65", "Kosmos-3M"),
    (r"^Kosmos 65S3", "Kosmos-3"),
    (r"^Kosmos 11K63|^Kosmos 63S1", "Kosmos-2"),
    (r"^Ariane 5", "Ariane 5"),
    (r"^Ariane 4", "Ariane 4"),
    (r"^Ariane 6", "Ariane 6"),
    (r"^H-IIA", "H-IIA"),
    (r"^H-IIB", "H-IIB"),
    (r"^H3", "H3"),
    (r"^Thorad", "Thorad-Agena"),
    (r"^Thor .*Agena|^Thor Agena", "Thor-Agena"),
    (r"^Thor Ablestar|^Thor Able", "Thor-Able"),
    (r"^Titan III", "Titan III"),
    (r"^Titan IV", "Titan IV"),
    (r"^PSLV", "PSLV"),
    (r"^GSLV", "GSLV"),
    (r"^Zenit", "Zenit"),
    (r"^Pegasus", "Pegasus"),
    (r"^Electron", "Electron"),
    (r"^Vostok", "Vostok"),
    (r"^Molniya", "Molniya"),
    (r"^Voskhod", "Voskhod"),
    (r"^Tsiklon-3", "Tsiklon-3"),
    (r"^Tsiklon-2", "Tsiklon-2"),
    (r"^Atlas .*Centaur|^Atlas II|^Atlas III", "Atlas-Centaur"),
    (r"^Vega", "Vega"),
]


def family(lv: str | None) -> str:
    if not isinstance(lv, str) or not lv or lv == "-":
        return "Unknown"
    for pat, rep in RULES:
        if re.match(pat, lv):
            return re.sub(pat + r".*$", rep, lv) if "\\1" in rep else rep
    return lv


def compute(objects: pd.DataFrame, launches: pd.DataFrame, since_year: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    L = launches.copy()
    L["family"] = L["lv_type"].map(family)
    L["orbital"] = L["launch_code"].fillna("").str.startswith("O")
    o = objects.merge(L[["launch_tag", "family", "launch_ts"]], on="launch_tag", how="left")
    o["family"] = o["family"].fillna("Unknown")
    if since_year:
        L = L[L["launch_ts"].dt.year >= since_year]
        o = o[o["launch_ts"].dt.year >= since_year]
    stages = o[o["type_class"] == "R"]
    stage_ids = set(stages["jcat"])
    deb = o[(o["type_class"] == "D") & o["parent"].isin(stage_ids)]
    from kessler.build import parse_gcat_sdate

    deb = deb.assign(sdate_ts=pd.to_datetime(deb["sdate"].map(lambda s: parse_gcat_sdate(s)[0]), utc=True))
    per_stage = deb.groupby("parent").agg(pieces=("jcat", "size"), first_debris_ts=("sdate_ts", "min"))
    st = stages.set_index("jcat")
    per_stage = per_stage.join(st[["name", "family", "ldate_ts", "launch_tag"]], how="left")
    per_stage["days_to_first"] = (pd.to_datetime(per_stage["first_debris_ts"], utc=True) - per_stage["ldate_ts"]).dt.total_seconds() / 86400
    frag = per_stage[per_stage["pieces"] >= FRAG_MIN]

    g = pd.DataFrame(index=sorted(set(o["family"]) | set(L["family"])))
    g["launches"] = L[L["orbital"]].groupby("family").size()
    g["rb_total"] = stages.groupby("family").size()
    g["rb_in_orbit"] = stages[stages["status"].fillna("").str.startswith("O")].groupby("family").size()
    g["stage_debris"] = deb.groupby("family").size()
    g["stage_debris_in_orbit"] = deb[deb["status"].fillna("").str.startswith("O")].groupby("family").size()
    g["frag_events"] = frag.groupby("family").size()
    g["median_days_to_first_debris"] = frag[frag["days_to_first"] >= 0].groupby("family")["days_to_first"].median()
    g = g.fillna({c: 0 for c in ("launches", "rb_total", "rb_in_orbit", "stage_debris", "stage_debris_in_orbit", "frag_events")})
    for c in ("launches", "rb_total", "rb_in_orbit", "stage_debris", "stage_debris_in_orbit", "frag_events"):
        g[c] = g[c].astype(int)
    g["debris_per_launch"] = np.where(g["launches"] > 0, g["stage_debris"] / g["launches"].clip(lower=1), np.nan)
    g = g[(g.index != "Unknown") & ((g["launches"] >= 10) | (g["stage_debris"] >= 50) | g.index.isin(HIGHLIGHT))]
    g["highlight"] = g.index.isin(HIGHLIGHT)
    g = g.sort_values("stage_debris", ascending=False)
    keep = set(g.head(28).index) | (set(g.index) & HIGHLIGHT)
    g = g[g.index.isin(keep)].reset_index(names="family")
    events = frag.reset_index().sort_values("first_debris_ts", ascending=False)
    return g, events


def build_scorecard(wh, site: Path, tables_dir: Path) -> None:
    from kessler.build import _json, _write_table

    if wh.gcat_objects.empty or wh.gcat_launches.empty:
        return
    release = wh.state.get("gcat_release") or (wh.gcat_objects["gcat_release"].iloc[0] if "gcat_release" in wh.gcat_objects else "GCAT")
    rows_all, events = compute(wh.gcat_objects, wh.gcat_launches)
    rows_recent, _ = compute(wh.gcat_objects, wh.gcat_launches, since_year=2000)

    def ser(df: pd.DataFrame) -> list[dict]:
        out = []
        for r in df.itertuples():
            out.append({
                "family": r.family, "launches": int(r.launches), "rb_in_orbit": int(r.rb_in_orbit), "rb_total": int(r.rb_total),
                "stage_debris": int(r.stage_debris), "stage_debris_in_orbit": int(r.stage_debris_in_orbit), "frag_events": int(r.frag_events),
                "debris_per_launch": None if pd.isna(r.debris_per_launch) else round(float(r.debris_per_launch), 3),
                "median_days_to_first_debris": None if pd.isna(r.median_days_to_first_debris) else round(float(r.median_days_to_first_debris), 1),
                "highlight": bool(r.highlight),
            })
        return out

    ev = []
    for r in events.head(60).itertuples():
        t = r.first_debris_ts
        ev.append({"parent": r.parent, "name": str(r.name), "family": str(r.family), "date": None if t is None or pd.isna(t) else pd.Timestamp(t).date().isoformat(), "pieces": int(r.pieces), "launch_tag": str(r.launch_tag)})
    citation = f"McDowell, Jonathan C., 2020. General Catalog of Artificial Space Objects, Release {release}, https://planet4589.org/space/gcat"
    _json(site / "scorecard.json", {"gcat_release": release, "citation": citation, "since_year": 2000, "rows": ser(rows_all), "rows_recent": ser(rows_recent), "events": ev, "frag_min": FRAG_MIN})
    _write_table(tables_dir, "scorecard", rows_all.assign(scope="all"))
