"""`kessler build`: compute derived tables and site products from the warehouse.

Outputs (under ``build_dir``):
  site/…            JSON/bin products in the frontend contract (plan §8.4), copied by `kessler export`
  tables/*.parquet  derived tables (plan §8.2); a curated subset becomes the SQL Lab's sql/*.parquet
"""

from __future__ import annotations

import json
import re
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from rich.console import Console

from kessler import __version__, config
from kessler.export.ephem import build_ephemeris
from kessler.forensics import deltav, epoch_solver, membership, parent_only
from kessler.forensics.gabbard import gabbard_points
from kessler.orbits.elements import apogee_alt_km, perigee_alt_km
from kessler.warehouse import store

console = Console(stderr=True)
SOLVER_VERSION = f"kessler-{__version__}/hybrid-1"


# ----------------------------------------------------------------------------- helpers
def _json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(obj), separators=(",", ":"), default=str, allow_nan=False))


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return None if pd.isna(o) else o.isoformat()
    if o is pd.NaT or (o is not None and not isinstance(o, (str, bytes, dict, list)) and pd.api.types.is_scalar(o) and pd.isna(o)):
        return None
    return o


def _iso(t) -> str | None:
    return None if t is None or pd.isna(t) else pd.Timestamp(t).isoformat()


class Warehouse:
    """Loads the tables a build needs once."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.gp = store.read(root, "gp_elements")
        if not self.gp.empty:
            self.gp["epoch"] = pd.to_datetime(self.gp["epoch"], utc=True)
            self.gp["norad_cat_id"] = self.gp["norad_cat_id"].astype("int64")
            self.gp = self.gp.sort_values(["norad_cat_id", "epoch"]).drop_duplicates(["norad_cat_id", "epoch"])
        sat = store.read(root, "satcat")
        if not sat.empty:
            sat = sat.sort_values("fetched_at").drop_duplicates("norad_cat_id", keep="last")
            sat["norad_cat_id"] = sat["norad_cat_id"].astype("int64")
        self.satcat = sat
        self.gcat_objects = store.read(root, "gcat_objects")
        self.gcat_launches = store.read(root, "gcat_launches")
        self.space_weather = store.read(root, "space_weather")
        self.kp_live = store.read(root, "kp_live")
        self.forecasts = store.read(root, "reentry_forecasts")
        state = self.root / "_state.json"
        self.state = json.loads(state.read_text()) if state.exists() else {}

    def decay_map(self) -> dict[int, pd.Timestamp]:
        if self.satcat.empty:
            return {}
        d = pd.to_datetime(self.satcat["decay_date"], errors="coerce", utc=True)
        m = d.notna()
        return dict(zip(self.satcat.loc[m, "norad_cat_id"].astype(int), d[m], strict=False))


GCAT_SDATE = re.compile(r"^(\d{4}) (\w{3})\s+(\d{1,2})(?:\s+(\d{2})(\d{2}))?")


def parse_gcat_sdate(s: str) -> tuple[pd.Timestamp | None, bool]:
    """'2026 Sep 13 2113' -> (timestamp, has_time)."""
    m = GCAT_SDATE.match((s or "").strip())
    if not m:
        return None, False
    y, mon, d, hh, mm = m.groups()
    try:
        t = pd.Timestamp(f"{y} {mon} {d} {hh or '00'}:{mm or '00'}", tz="UTC")
    except ValueError:
        return None, False
    return t, hh is not None


def gcat_reference(wh: Warehouse, parent_norad: int, ref: pd.Timestamp) -> dict | None:
    g = wh.gcat_objects
    if g.empty:
        return None
    pj = g.loc[g["satcat_num"] == parent_norad, "jcat"]
    if pj.empty:
        return None
    deb = g[(g["parent"] == pj.iloc[0]) & (g["type_class"] == "D")]
    times = []
    for s in deb["sdate"].dropna():
        t, has_time = parse_gcat_sdate(s)
        if t is not None and abs((t - ref).total_seconds()) < 60 * 86400:
            times.append((t, has_time))
    if not times:
        return None
    ser = pd.Series([t for t, _ in times])
    mode = ser.mode().iloc[0]
    has_time = any(h for t, h in times if t == mode)
    return {"label": f"GCAT debris separation date ({len(times)} objects)", "time": mode.isoformat(), "kind": "gcat", "has_time": has_time}


# ----------------------------------------------------------------------------- events
def solve_event(warehouse: Path, event_id: str) -> dict:
    wh = Warehouse(warehouse)
    ev = next(e for e in config.load_events() if e.id == event_id)
    return _event(wh, ev, Path("/tmp/kessler-solve"), write=False)["summary"]


def _event(wh: Warehouse, ev: config.Event, site: Path, write: bool = True) -> dict:
    cfg = config.settings()
    fz = cfg["forensics"]
    ex = cfg["export"]
    ref = pd.Timestamp(ev.reference_time).tz_convert("UTC")
    parent_norad = int(ev.norad)
    intdes = ev.intdes or ""
    gp = wh.gp
    gp_ev = gp[(gp["object_id"].fillna("").str.startswith(intdes)) | (gp["norad_cat_id"] == parent_norad)] if intdes else gp[gp["norad_cat_id"] == parent_norad]
    decay = wh.decay_map()
    sat = wh.satcat
    sc_parent = sat[sat["norad_cat_id"] == parent_norad]
    parent_name = ev.object_name or (sc_parent["object_name"].iloc[0] if len(sc_parent) else str(parent_norad))
    flags: list[str] = []
    if ev.stretch:
        flags.append("STRETCH")

    # ---- membership --------------------------------------------------------------------
    cands, msum = membership.assign_members(
        parent_norad, intdes, ref, gp_ev, sat if not sat.empty else pd.DataFrame(columns=["object_id", "norad_cat_id", "object_type"]),
        eps_deg=fz["dbscan_eps_deg"], min_samples=fz["dbscan_min_samples"],
    ) if intdes else (pd.DataFrame(columns=["norad_cat_id", "in_event"]), {"counts": {}, "parent_plane": None})
    members = cands[cands["in_event"]] if len(cands) else cands
    member_ids = [int(x) for x in members["norad_cat_id"]] if len(members) else []

    # ---- parent element set nearest the reference ---------------------------------------
    pgp = gp_ev[gp_ev["norad_cat_id"] == parent_norad].sort_values("epoch")
    parent_row = None
    if len(pgp):
        parent_row = pgp.loc[(pgp["epoch"] - ref).abs().idxmin()]

    # ---- references ------------------------------------------------------------------------
    references = [{"label": r.label, "time": r.time.isoformat(), "kind": "registry", "dv_ms": r.dv_ms} for r in ev.reference_sources]
    references += [{"label": r.label, "time": r.time.isoformat(), "kind": "alt", "dv_ms": r.dv_ms} for r in ev.alt_references]
    gref = gcat_reference(wh, parent_norad, ref)
    if gref:
        references.append(gref)

    # ---- solve -------------------------------------------------------------------------------
    solution = None
    alt_solutions = []
    dv = pd.DataFrame()
    mgp = gp_ev[gp_ev["norad_cat_id"].isin(member_ids)].sort_values("epoch")
    firsts = mgp.groupby("norad_cat_id").head(1)
    seconds = mgp.groupby("norad_cat_id").nth(1)
    ref_pairs = [(r["label"], pd.Timestamp(r["time"])) for r in references]
    if parent_row is not None and len(firsts) >= 1:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sol = epoch_solver.solve(
                parent_row, firsts, ref, method="hybrid", n_boot=fz["bootstrap"], low_conf_km=fz["low_confidence_spread_km"],
                min_fragments=fz["min_fragments"], second_sets=seconds if len(seconds) >= 2 else None, references=ref_pairs,
            )
            alt = epoch_solver.solve(parent_row, firsts, ref, method="sgp4-spread", n_boot=200, low_conf_km=fz["low_confidence_spread_km"], min_fragments=fz["min_fragments"])
        solution = sol
        alt_solutions.append(alt)
        if sol.t_p50 is not None:
            used = firsts[firsts["norad_cat_id"].isin(sol.used_norads)] if sol.used_norads else firsts
            dv = deltav.fragment_dv(parent_row, firsts, sol.t_p50)
            dv["used"] = dv["norad_cat_id"].isin(used["norad_cat_id"]) & dv["reliable"]
    elif len(firsts) == 0:
        flags.append("NO_PUBLIC_FRAGMENTS")

    po = parent_only.analyse(pgp, ref) if len(pgp) else None
    mode = "fragments" if (solution is not None and solution.t_p50 is not None) else ("parent_only" if po and po["n_elsets"] >= 2 else "insufficient")
    if mode != "fragments":
        flags.append("PARENT_ONLY")
        if po:
            flags.extend(f for f in po["flags"] if f not in flags)
    if solution is not None:
        flags.extend(f for f in solution.flags if f not in flags)

    # ---- validation against the primary registry reference --------------------------------
    validation = None
    if ev.reference_sources:
        r0 = ev.reference_sources[0]
        delta = None
        within = None
        if solution is not None and solution.t_p50 is not None:
            delta = (solution.t_p50 - pd.Timestamp(r0.time)).total_seconds() / 60
            within = abs(delta) <= ev.reference_precision_hours * 60
        validation = {"ref_time": r0.time.isoformat(), "ref_label": r0.label, "delta_min": delta, "within_precision": within, "precision_hours": ev.reference_precision_hours}
    for r in references:
        if solution is not None and solution.t_p50 is not None:
            r["delta_min"] = round((solution.t_p50 - pd.Timestamp(r["time"])).total_seconds() / 60, 2)

    # ---- fragments table + Gabbard ------------------------------------------------------------
    latest = gp_ev.sort_values("epoch").groupby("norad_cat_id").tail(1).set_index("norad_cat_id")
    frag_rows = []
    dvm = dv.set_index("norad_cat_id") if len(dv) else None
    for r in members.itertuples() if len(members) else []:
        n = int(r.norad_cat_id)
        lr = latest.loc[n] if n in latest.index else None
        frag_rows.append(
            {
                "norad": n,
                "name": str(r.object_name) if pd.notna(r.object_name) else f"{n}",
                "first_epoch": _iso(r.first_epoch),
                "decay_date": None if n not in decay else decay[n].date().isoformat(),
                "assignment": r.assignment_method,
                "dv_ms": None if dvm is None or n not in dvm.index or not bool(dvm.loc[n, "reliable"]) else round(float(dvm.loc[n, "dv_mag"]), 2),
                "apogee_km": None if lr is None else round(float(apogee_alt_km(lr["mean_motion"], lr["eccentricity"])), 1),
                "perigee_km": None if lr is None else round(float(perigee_alt_km(lr["mean_motion"], lr["eccentricity"])), 1),
                "forecast_p50": None,
            }
        )
    gab = gabbard_points(gp_ev, [parent_norad, *member_ids], parent_norad, decay)
    if len(gab) > ex["gabbard_max_rows"]:
        gab = gab.sample(ex["gabbard_max_rows"], random_state=0).sort_values(["snapshot", "norad_cat_id"])
    latest_snap = gab[gab["snapshot"] == gab["snapshot"].max()] if len(gab) else gab
    sparkline = [{"period": round(r.period, 3), "apo": round(r.apo, 1), "peri": round(r.peri, 1), "parent": bool(r.parent)} for r in latest_snap.head(80).itertuples()]

    # ---- decay curve -----------------------------------------------------------------------
    decay_curve = []
    if member_ids:
        start = (solution.t_p50 if solution is not None and solution.t_p50 is not None else ref).floor("D")
        days = pd.date_range(start, pd.Timestamp.now(tz="UTC").floor("D"), freq="D")
        dd = [decay.get(n) for n in member_ids]
        for d in days:
            catalogued = sum(1 for r in frag_rows if r["first_epoch"] and pd.Timestamp(r["first_epoch"]) <= d + pd.Timedelta(days=1))
            gone = sum(1 for x in dd if x is not None and x <= d)
            decay_curve.append({"date": d.date().isoformat(), "remaining": len(member_ids) - gone, "catalogued": catalogued})

    # ---- membership explainer --------------------------------------------------------------
    clusters = []
    pp = msum.get("parent_plane")
    for r in cands.itertuples() if len(cands) else []:
        if pd.isna(getattr(r, "raan", np.nan)):
            continue
        draan = ((r.raan - pp["raan"] + 180) % 360) - 180 if pp else r.raan
        clusters.append(
            {
                "norad": int(r.norad_cat_id),
                "name": str(r.object_name),
                "label": int(r.cluster_label),
                "assignment": r.assignment_method,
                "first_epoch": _iso(r.first_epoch),
                "x": round(float(draan), 3),
                "y": round(float(r.inc), 4),
                "inc": round(float(r.inc), 4),
                "raan": round(float(r.raan), 3),
                "in_event": bool(r.in_event),
            }
        )
    if pp:
        clusters.append({"norad": parent_norad, "name": parent_name, "label": int(msum["parent_label"]), "assignment": "parent", "first_epoch": None, "x": 0.0, "y": round(pp["inc"], 4), "inc": round(pp["inc"], 4), "raan": round(pp["raan"], 3), "in_event": True})
    counts = msum.get("counts", {})
    explain = _membership_text(counts, ev)

    # ---- ephemeris ---------------------------------------------------------------------------
    ephem_info = {"available": False, "reason": "no parent element sets"}
    t0 = solution.t_p50 if (solution is not None and solution.t_p50 is not None) else ref
    if parent_row is not None:
        objs = pd.DataFrame({"norad_cat_id": [parent_norad] + member_ids, "name": [parent_name] + [r["name"] for r in frag_rows]})
        arr, meta = build_ephemeris(
            t0, objs, gp_ev, parent_norad, dv if len(dv) else None, decay,
            dense_hours=ex["ephem_dense_hours"], dense_step_s=ex["ephem_dense_step_s"], daily_days=ex["ephem_daily_days"],
        )
        if solution is not None and solution.lat is not None:
            meta["breakup"] = {"lat": solution.lat, "lon": solution.lon, "alt_km": solution.alt_km}
        else:
            meta["breakup"] = None
        meta["t0_kind"] = "solution" if solution is not None and solution.t_p50 is not None else "reference"
        if write:
            d = site / "events" / ev.id
            d.mkdir(parents=True, exist_ok=True)
            (d / "ephem.bin").write_bytes(arr.tobytes())
            _json(d / "ephem.meta.json", meta)
        ephem_info = {"available": True, "reconstructed": meta["reconstructed"], "t0_kind": meta["t0_kind"]}

    sol_dict = solution.as_dict() if solution is not None else None
    summary = {
        "id": ev.id,
        "title": ev.title,
        "blurb": ev.blurb.strip(),
        "regime": ev.regime,
        "mode": mode,
        "stretch": ev.stretch,
        "parent": {"norad": parent_norad, "name": parent_name, "intdes": intdes},
        "reference_time": ref.isoformat(),
        "reference_precision_hours": ev.reference_precision_hours,
        "reference_note": ev.reference_note,
        "references": references,
        "solution": sol_dict,
        "alt_solutions": [a.as_dict() for a in alt_solutions],
        "parent_only": po,
        "membership": {"counts": counts, "candidates": int(len(cands)), "clusters": clusters, "explain": explain},
        "dv_stats": deltav.dv_stats(dv[dv["used"]]) if len(dv) else None,
        "fragments": frag_rows,
        "decay_curve": decay_curve,
        "ephem": ephem_info,
        "flags": flags,
        "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "solver_version": SOLVER_VERSION,
    }
    index_entry = {
        "id": ev.id,
        "title": ev.title,
        "regime": ev.regime,
        "mode": mode,
        "parent_norad": parent_norad,
        "parent_name": parent_name,
        "t_p50": sol_dict["t_p50"] if sol_dict else None,
        "t_p05": sol_dict["t_p05"] if sol_dict else None,
        "t_p95": sol_dict["t_p95"] if sol_dict else None,
        "n_fragments": len(member_ids),
        "n_decayed": sum(1 for n in member_ids if n in decay),
        "alt_km": (sol_dict or {}).get("alt_km") or (round(float(latest_snap.loc[latest_snap["parent"], "apo"].mean()), 0) if len(latest_snap) and latest_snap["parent"].any() else None),
        "flags": flags,
        "validation": validation,
        "stretch": ev.stretch,
        "sparkline": sparkline,
    }
    if write:
        d = site / "events" / ev.id
        _json(d / "summary.json", summary)
        _json(
            d / "gabbard.json",
            [{"norad": int(r.norad_cat_id), "epoch": _iso(r.epoch), "snapshot": _iso(r.snapshot), "period": round(r.period, 4), "apo": round(r.apo, 2), "peri": round(r.peri, 2), "parent": bool(r.parent)} for r in gab.itertuples()],
        )
        _json(
            d / "dv.json",
            [{"norad": int(r.norad_cat_id), "r": round(r.dv_r, 3), "t": round(r.dv_t, 3), "n": round(r.dv_n, 3), "mag": round(r.dv_mag, 3), "residual_km": round(r.residual_km, 2) if np.isfinite(r.residual_km) else None, "used": bool(r.used), "reliable": bool(r.reliable)} for r in dv.itertuples()] if len(dv) else [],
        )
    tables = {
        "event_fragments": pd.DataFrame(
            [{"event_id": ev.id, "norad_cat_id": int(r.norad_cat_id), "object_name": str(r.object_name), "assignment_method": r.assignment_method,
              "cluster_label": None if pd.isna(getattr(r, "cluster_label", np.nan)) else int(r.cluster_label), "first_epoch": r.first_epoch, "in_event": bool(r.in_event)}
             for r in cands.itertuples()] if len(cands) else []
        ),
        "fragment_dv": dv.assign(event_id=ev.id) if len(dv) else pd.DataFrame(),
        "gabbard_points": gab.assign(event_id=ev.id) if len(gab) else pd.DataFrame(),
    }
    return {"summary": summary, "index": index_entry, "tables": tables, "solution": solution}


def _membership_text(c: dict, ev: config.Event) -> str:
    if not c:
        return "No international designator is registered for this event, so membership was not evaluated."
    parts = [f"{c.get('intdes_candidates', 0)} debris objects share the designator {ev.intdes}."]
    if c.get("decayed_before_event"):
        parts.append(f"{c['decayed_before_event']} had already reentered before the event.")
    parts.append(f"{c.get('pass_time_filter', 0)} were first catalogued after the reference time.")
    if c.get("cluster_confirmed"):
        parts.append(f"{c['cluster_confirmed']} of those share the parent's orbital-plane cluster at the event epoch.")
    parts.append(f"{c.get('members', 0)} are counted as fragments of this event.")
    if ev.prior_breakups and c.get("members", 0) == 0:
        parts.append(
            "Every catalogued piece predates this event (prior breakups: " + ", ".join(ev.prior_breakups)
            + "). No debris from the new fragmentation has been published in the public catalog yet."
        )
    return " ".join(parts)


# ----------------------------------------------------------------------------- top level
def run_build(warehouse: Path, build_dir: Path) -> None:
    build_dir = Path(build_dir)
    site = build_dir / "site"
    tables_dir = build_dir / "tables"
    for d in (site, tables_dir):
        d.mkdir(parents=True, exist_ok=True)
    wh = Warehouse(warehouse)
    if wh.gp.empty:
        console.print("[yellow]warehouse has no GP data; nothing to build[/yellow]")
        return

    index, solutions, collected = [], [], {"event_fragments": [], "fragment_dv": [], "gabbard_points": []}
    for ev in config.load_events():
        if not ev.norad:
            continue
        console.print(f"event {ev.id} …")
        try:
            out = _event(wh, ev, site)
        except Exception as e:  # one bad event must not take the site down
            console.print(f"[red]event {ev.id} failed:[/red] {e!r}")
            import traceback

            traceback.print_exc()
            continue
        index.append(out["index"])
        s = out["summary"]["solution"]
        solutions.append(
            {"event_id": ev.id, "t_p05": s and s["t_p05"], "t_p50": s and s["t_p50"], "t_p95": s and s["t_p95"], "lat": s and s["lat"], "lon": s and s["lon"],
             "alt_km": s and s["alt_km"], "spread_km": s and s["spread_km"], "n_used": s["n_used"] if s else 0, "flags": ",".join(out["index"]["flags"]),
             "solver_version": SOLVER_VERSION, "computed_at": out["summary"]["computed_at"]}
        )
        for k, df in out["tables"].items():
            if len(df):
                collected[k].append(df)
        console.print(f"  mode={out['index']['mode']} fragments={out['index']['n_fragments']} t*={out['index']['t_p50']} flags={out['index']['flags']}")

    order = {e.id: i for i, e in enumerate(config.load_events())}
    index.sort(key=lambda e: (e["stretch"], e["mode"] != "fragments", order.get(e["id"], 99)))
    _json(site / "events" / "index.json", index)

    events_tbl = pd.DataFrame(
        [{"event_id": e["id"], "title": e["title"], "regime": e["regime"], "mode": e["mode"], "parent_norad": e["parent_norad"], "parent_name": e["parent_name"],
          "n_fragments": e["n_fragments"], "n_decayed": e["n_decayed"], "t_p50": e["t_p50"], "reference_delta_min": (e["validation"] or {}).get("delta_min")} for e in index]
    )
    _write_table(tables_dir, "events", events_tbl)
    _write_table(tables_dir, "breakup_solutions", pd.DataFrame(solutions))
    for k, frames in collected.items():
        if frames:
            _write_table(tables_dir, k, pd.concat(frames, ignore_index=True))

    _space_weather(wh, site)

    # reentry + scorecard (later phases plug in here)
    try:
        from kessler.reentry.products import build_reentry

        build_reentry(wh, site, tables_dir, index)
    except ImportError:
        pass
    try:
        from kessler.scorecard.gcat_stats import build_scorecard

        build_scorecard(wh, site, tables_dir)
    except ImportError:
        pass
    console.print(f"[green]build complete[/green] → {build_dir}")


TS_COLS = {"t_p05", "t_p50", "t_p95", "computed_at", "first_epoch", "epoch", "snapshot", "issued_at", "p10", "p50", "p90", "baseline"}


def _write_table(d: Path, name: str, df: pd.DataFrame) -> None:
    """Derived tables store naive UTC timestamps: DuckDB-WASM ships without ICU, which time-zone-aware
    columns need for casts like ``ts::DATE``. All times are UTC."""
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object:
            sample = df[c].dropna()
            if len(sample) and isinstance(sample.iloc[0], pd.Timestamp | str) and c in TS_COLS:
                df[c] = pd.to_datetime(df[c], utc=True, format="ISO8601")
        if isinstance(df[c].dtype, pd.DatetimeTZDtype):
            df[c] = df[c].dt.tz_convert("UTC").dt.tz_localize(None)
    df.to_parquet(d / f"{name}.parquet", index=False, compression="zstd")


def _space_weather(wh: Warehouse, site: Path) -> None:
    sw = wh.space_weather
    daily = []
    if not sw.empty:
        sw = sw.copy()
        sw["date"] = pd.to_datetime(sw["date"], utc=True)
        now = pd.Timestamp.now(tz="UTC")
        sw = sw[(sw["date"] >= now - pd.Timedelta(days=400)) & (sw["date"] <= now + pd.Timedelta(days=45))].sort_values("date")
        for r in sw.itertuples():
            daily.append({"date": r.date.date().isoformat(), "f107": r.f107_obs, "f107_81": r.f107_obs_center81, "ap": r.ap_avg, "kp_max": r.kp_max, "type": r.f107_data_type})
    kp = []
    if not wh.kp_live.empty:
        k = wh.kp_live.copy()
        k["time_tag"] = pd.to_datetime(k["time_tag"], utc=True)
        k = k.sort_values("time_tag").tail(8 * 30)
        kp = [{"t": r.time_tag.isoformat(), "kp": r.kp} for r in k.itertuples()]
    _json(site / "spaceweather.json", {"daily": daily, "kp_live": kp})
