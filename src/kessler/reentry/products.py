"""Reentry site products: forecasts.json, backtest.json, calibration.json and SQL tables."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from rich.console import Console

from kessler.reentry.dataset import training_set
from kessler.reentry.evaluate import backtest

console = Console(stderr=True)


def build_reentry(wh, site: Path, tables_dir: Path, index: list[dict]) -> None:
    from kessler.build import _json, _write_table

    ds = training_set(wh.gp, wh.satcat, wh.space_weather) if not wh.gp.empty and not wh.satcat.empty else pd.DataFrame()
    console.print(f"reentry: {len(ds)} labelled element sets from {ds['norad_cat_id'].nunique() if len(ds) else 0} objects")
    bt, _ = backtest(ds) if len(ds) else ({"metrics": [], "calibration": [], "lead_time": [], "notes": ["No labelled data yet."], "n_train": 0, "n_holdout": 0}, None)
    bt["generated_at"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")

    # ---- forecasts: latest per object, and scoring of earlier forecasts -------------------
    fc = wh.forecasts.copy()
    forecasts_json, scored = [], []
    if not fc.empty:
        for c in ("issued_at", "epoch", "p10", "p50", "p90", "baseline"):
            fc[c] = pd.to_datetime(fc[c], utc=True)
        decay = wh.decay_map()
        fc["actual"] = fc["norad_cat_id"].map(lambda n: decay.get(int(n)))
        done = fc[fc["actual"].notna()].copy()
        if len(done):
            done["actual_ts"] = pd.to_datetime(done["actual"], utc=True) + pd.Timedelta(hours=12)
            done["abs_err_days"] = (done["p50"] - done["actual_ts"]).abs().dt.total_seconds() / 86400
            done["inside80"] = (done["actual_ts"] >= done["p10"] - pd.Timedelta(hours=12)) & (done["actual_ts"] <= done["p90"] + pd.Timedelta(hours=12))
            done["lead_days"] = (done["actual_ts"] - done["issued_at"]).dt.total_seconds() / 86400
            for r in done.sort_values("issued_at").itertuples():
                scored.append({"norad": int(r.norad_cat_id), "name": str(r.object_name), "issued_at": r.issued_at.isoformat(), "p50": r.p50.isoformat(), "actual": pd.Timestamp(r.actual).date().isoformat(), "abs_err_days": round(float(r.abs_err_days), 2), "inside80": bool(r.inside80), "lead_days": round(float(r.lead_days), 2), "model_version": r.model_version})
        live = fc[fc["actual"].isna()].sort_values("issued_at").groupby("norad_cat_id").tail(1)
        live = live[live["issued_at"] >= live["issued_at"].max() - pd.Timedelta(days=2)]
        for r in live.sort_values("p50").itertuples():
            forecasts_json.append({
                "norad": int(r.norad_cat_id), "name": str(r.object_name), "object_type": str(r.object_type), "event_id": None if pd.isna(r.event_id) else str(r.event_id),
                "perigee_km": round(float(r.perigee_km), 1), "apogee_km": round(float(r.apogee_km), 1), "epoch": r.epoch.isoformat(), "issued_at": r.issued_at.isoformat(),
                "p10": r.p10.isoformat(), "p50": r.p50.isoformat(), "p90": r.p90.isoformat(), "baseline": r.baseline.isoformat(), "model_version": r.model_version,
            })
        out = fc.drop(columns=["actual"]).copy()
        _write_table(tables_dir, "reentry_forecasts", out)
    bt["scored_live"] = scored[-500:]
    if scored:
        bt["live_summary"] = {
            "n": len(scored),
            "mae_days": float(np.mean([s["abs_err_days"] for s in scored])),
            "coverage80": float(np.mean([s["inside80"] for s in scored])),
        }
    _json(site / "reentry" / "forecasts.json", forecasts_json)
    _json(site / "reentry" / "backtest.json", bt)
    _json(site / "reentry" / "calibration.json", bt.get("calibration", []))

    rows = []
    for m in bt.get("metrics", []):
        for k, v in m.items():
            if k != "model" and v is not None:
                rows.append({"fold": "holdout", "model": m["model"], "metric": k, "value": float(v)})
    if rows:
        _write_table(tables_dir, "reentry_backtest", pd.DataFrame(rows))
    if len(ds):
        agg = ds.groupby("norad_cat_id").agg(
            object_name=("object_name", "last"), object_type=("object_type", "last"), decay_date=("decay_date", "last"),
            n_elsets=("epoch", "size"), first_epoch=("epoch", "min"), last_epoch=("epoch", "max"),
            max_days_to_decay=("days_to_decay", "max"), min_days_to_decay=("days_to_decay", "min"), rcs=("rcs", "last"),
        ).reset_index()
        _write_table(tables_dir, "decayed_objects", agg)

    # ---- patch event summaries with fragment forecasts ------------------------------------
    by_norad = {f["norad"]: f for f in forecasts_json}
    for e in index:
        p = site / "events" / e["id"] / "summary.json"
        if not p.exists():
            continue
        s = json.loads(p.read_text())
        changed = False
        for frag in s.get("fragments", []):
            f = by_norad.get(frag["norad"])
            if f:
                frag["forecast_p50"] = f["p50"]
                changed = True
        if changed:
            p.write_text(json.dumps(s, separators=(",", ":")))
