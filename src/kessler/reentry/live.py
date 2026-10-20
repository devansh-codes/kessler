"""Issue live reentry forecasts and persist them with ``issued_at`` (run inside the ingest workflow,
which can write to the data branch), so every forecast can be scored once the object decays."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from rich.console import Console

from kessler import config
from kessler.reentry.dataset import TYPES, featurize, space_weather_daily, training_set
from kessler.reentry.model import MODEL_VERSION, QuantileModel
from kessler.warehouse import store

console = Console(stderr=True)
MAX_PERIGEE_KM = 450.0
MAX_BASELINE_DAYS = 120.0


def production_model(ds: pd.DataFrame) -> QuantileModel | None:
    if len(ds) < 200:
        return None
    ds = ds.sort_values("epoch")
    k = int(len(ds) * 0.8)
    m = QuantileModel().fit(ds.iloc[:k], ds["days_to_decay"].iloc[:k].to_numpy())
    m.calibrate(ds.iloc[k:], ds["days_to_decay"].iloc[k:].to_numpy())
    return m


def candidates(gp: pd.DataFrame, satcat: pd.DataFrame, sw: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    latest = gp.sort_values("epoch").groupby("norad_cat_id").tail(1)
    latest = latest[pd.to_datetime(latest["epoch"], utc=True) >= now - pd.Timedelta(days=4)]
    sc = satcat.copy()
    decayed = set(sc.loc[sc["decay_date"].notna(), "norad_cat_id"])
    latest = latest[~latest["norad_cat_id"].isin(decayed)]
    f = featurize(latest, sc, space_weather_daily(sw))
    # the model is trained on debris, rocket bodies and unknowns; payloads (often under active,
    # controlled deorbit) are outside its domain and are not forecast
    f = f[f["object_type"].isin(TYPES)]
    f = f[(f["perigee_km"] > 80) & ((f["perigee_km"] < MAX_PERIGEE_KM) | (f["baseline_days"] < MAX_BASELINE_DAYS))]
    events = config.load_events()
    def event_of(oid) -> str | None:
        for e in events:
            if e.intdes and isinstance(oid, str) and oid.startswith(e.intdes):
                return e.id
        return None
    f["event_id"] = f["object_id"].map(event_of)
    return f.reset_index(drop=True)


def issue_forecasts(warehouse: Path, now: datetime | None = None) -> int:
    warehouse = Path(warehouse)
    now_ts = pd.Timestamp(now or datetime.now(UTC)).floor("s")
    gp = store.read(warehouse, "gp_elements")
    sat = store.read(warehouse, "satcat")
    sw = store.read(warehouse, "space_weather")
    if gp.empty or sat.empty:
        return 0
    gp["epoch"] = pd.to_datetime(gp["epoch"], utc=True)
    sat = sat.sort_values("fetched_at").drop_duplicates("norad_cat_id", keep="last")
    ds = training_set(gp, sat, sw)
    model = production_model(ds)
    cand = candidates(gp, sat, sw, now_ts)
    if cand.empty:
        return 0
    prev = store.read(warehouse, "reentry_forecasts")
    if not prev.empty:
        seen = set(zip(prev["norad_cat_id"].astype(int), pd.to_datetime(prev["epoch"], utc=True), strict=False))
        cand = cand[[(int(n), pd.Timestamp(e)) not in seen for n, e in zip(cand["norad_cat_id"], pd.to_datetime(cand["epoch"], utc=True), strict=False)]]
    if cand.empty:
        console.print("no new element sets to forecast")
        return 0
    base = cand["baseline_days"].to_numpy()
    if model is not None:
        p50 = model.median(cand)
        lo, hi = model.interval(cand, 0.8)
        version = MODEL_VERSION
    else:
        p50, lo, hi = base, base * 0.5, base * 1.5
        version = "physics-baseline"
    ep = pd.to_datetime(cand["epoch"], utc=True)
    td = lambda d: pd.to_timedelta(np.asarray(d, dtype=float), unit="D")  # noqa: E731
    out = pd.DataFrame(
        {
            "norad_cat_id": cand["norad_cat_id"].astype("int64"),
            "issued_at": now_ts,
            "epoch": ep,
            "object_name": cand["object_name"].astype("string"),
            "object_type": cand["object_type"].astype("string"),
            "event_id": cand["event_id"].astype("string"),
            "perigee_km": cand["perigee_km"].astype(float),
            "apogee_km": cand["apogee_km"].astype(float),
            "p10": ep + td(lo),
            "p50": ep + td(p50),
            "p90": ep + td(hi),
            "baseline": ep + td(base),
            "model_version": version,
        }
    )
    n = store.write(warehouse, "reentry_forecasts", out)
    console.print(f"issued {n} forecasts with {version}")
    return n
