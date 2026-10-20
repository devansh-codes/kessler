"""manifest.json: provenance, attribution, file hashes and ingest status for the Status page."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from kessler.warehouse import store
from kessler.warehouse.schema import SCHEMA_VERSION, TABLES

SOURCES = [
    {
        "id": "celestrak_gp",
        "label": "CelesTrak GP (OMM element sets)",
        "url": "https://celestrak.org/NORAD/elements/",
        "license": "CelesTrak (Dr. T.S. Kelso), sourced from 18 SDS / Space-Track. No redistribution of raw element sets.",
        "tasks": ["gp_current", "gp_first", "gp_last", "gp_decaying", "reentry_backfill"],
    },
    {
        "id": "celestrak_satcat",
        "label": "CelesTrak SATCAT (metadata, decay dates)",
        "url": "https://celestrak.org/satcat/",
        "license": "CelesTrak",
        "tasks": ["satcat"],
    },
    {
        "id": "celestrak_sw",
        "label": "CelesTrak space weather (F10.7, Ap, Kp)",
        "url": "https://celestrak.org/SpaceData/",
        "license": "CelesTrak SpaceData",
        "tasks": ["space_weather"],
    },
    {
        "id": "noaa_swpc",
        "label": "NOAA SWPC live Kp and F10.7",
        "url": "https://www.swpc.noaa.gov/",
        "license": "Public domain (US Government)",
        "tasks": ["swpc"],
    },
    {
        "id": "gcat",
        "label": "GCAT (launch and stage lineage)",
        "url": "https://planet4589.org/space/gcat",
        "license": "CC-BY 4.0. McDowell, Jonathan C., 2020. General Catalog of Artificial Space Objects",
        "tasks": ["gcat"],
    },
    {
        "id": "nasa",
        "label": "NASA Visible Earth (Blue Marble texture)",
        "url": "https://visibleearth.nasa.gov/",
        "license": "Public domain",
        "tasks": [],
    },
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(warehouse: Path, out: Path) -> dict:
    warehouse = Path(warehouse)
    state_path = warehouse / "_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    last_success = state.get("last_success", {})
    sources = []
    for s in SOURCES:
        times = [v for k, v in last_success.items() if any(k == t or k.startswith(t + ":") for t in s["tasks"])]
        sources.append({k: v for k, v in s.items() if k != "tasks"} | {"last_success": max(times) if times else None})

    log = store.read(warehouse, "ingest_log")
    http = []
    if not log.empty:
        log = log.sort_values(["started_at", "seq"]).tail(200)
        for r in log.itertuples():
            http.append(
                {
                    "url": r.url,
                    "host": r.host,
                    "status": None if pd.isna(r.status) else int(r.status),
                    "from_cache": bool(r.from_cache),
                    "started_at": pd.Timestamp(r.started_at).isoformat(),
                    "bytes": int(r.bytes),
                    "duration_ms": int(r.duration_ms),
                    "error": None if pd.isna(r.error) else str(r.error),
                }
            )
    table_rows = {}
    for t in TABLES:
        files = list((warehouse / t).rglob("part-*.parquet"))
        if files:
            import pyarrow.parquet as pq

            table_rows[t] = int(sum(pq.ParquetFile(f).metadata.num_rows for f in files))
    last_run = state.get("last_run")
    files = {}
    for p in sorted(Path(out).rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            files[p.relative_to(out).as_posix()] = sha256(p)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "schema_version": SCHEMA_VERSION,
        "gcat_release": state.get("gcat_release"),
        "publish_raw_omm": os.environ.get("PUBLISH_RAW_OMM", "false").lower() == "true",
        "sources": sources,
        "files": files,
        "ingest_status": {
            "last_run": {k: v for k, v in last_run.items() if k != "tasks"} if last_run else None,
            "runs": state.get("runs", [])[-40:],
            "tasks": last_run.get("tasks", []) if last_run else [],
            "http": http,
            "table_rows": table_rows,
            "backfill_remaining": state.get("backfill_remaining"),
        },
    }
