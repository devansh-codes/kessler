"""Ingest orchestration: one polite, sequential pass over every source.

Cadence is tracked in ``warehouse/_state.json`` (it lives on the data branch, so it survives across
ephemeral CI runners); the on-disk HTTP cache adds a second, 2-hour guard against re-requests.

Failure policy: the first non-200 from a host family stops every further request to that family for
the rest of the run (CelesTrak never sees a retry). Other families continue. The run finishes with
``status=partial`` and every request is recorded in ``ingest_log``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from rich.console import Console

from kessler import config
from kessler.http import HttpStop, PoliteClient
from kessler.sources import celestrak_gp, celestrak_satcat, celestrak_sw, gcat, swpc
from kessler.warehouse import store

console = Console(stderr=True)


@dataclass
class IngestResult:
    run_id: str
    started_at: datetime
    status: str = "ok"
    tasks: list[dict] = field(default_factory=list)
    network_calls: int = 0
    rows_new: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "status": self.status,
            "network_calls": self.network_calls,
            "rows_new": self.rows_new,
            "tasks": self.tasks,
        }


class State:
    """Per-source last-success timestamps + small bookkeeping, persisted on the data branch."""

    def __init__(self, warehouse: Path):
        self.path = Path(warehouse) / "_state.json"
        self.data: dict = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.data.setdefault("last_success", {})
        self.data.setdefault("backfill_done", [])

    def due(self, key: str, every_s: float, now: datetime) -> bool:
        last = self.data["last_success"].get(key)
        if last is None:
            return True
        return (now - datetime.fromisoformat(last)).total_seconds() >= every_s

    def mark(self, key: str, now: datetime) -> None:
        self.data["last_success"][key] = now.isoformat(timespec="seconds")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1, sort_keys=True) + "\n")


def run_ingest(
    warehouse: Path,
    cache_dir: Path,
    now: datetime | None = None,
    clients: dict[str, PoliteClient] | None = None,
    events: list[config.Event] | None = None,
    only: set[str] | None = None,
) -> IngestResult:
    now = now or datetime.now(UTC)
    warehouse = Path(warehouse)
    cfg = config.settings()
    cad = cfg["cadence_s"]
    events = events if events is not None else config.load_events()
    clients = clients or {
        "celestrak": PoliteClient(Path(cache_dir) / "celestrak"),
        "noaa": PoliteClient(Path(cache_dir) / "noaa"),
        "gcat": PoliteClient(Path(cache_dir) / "gcat"),
    }
    ct, noaa, gc = clients["celestrak"], clients["noaa"], clients["gcat"]
    state = State(warehouse)
    res = IngestResult(run_id=now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6], started_at=now)

    def task(name: str, client: PoliteClient, every_s: float, fn: Callable[[], dict[str, int]]) -> None:
        if only and not any(name.startswith(o) for o in only):
            return
        if not state.due(name, every_s, now):
            res.tasks.append({"task": name, "status": "skipped (not due)"})
            return
        if client.stopped:
            res.tasks.append({"task": name, "status": "skipped (host stopped after error)"})
            res.status = "partial"
            return
        try:
            added = fn()
        except HttpStop as e:
            res.status = "partial"
            res.tasks.append({"task": name, "status": "error", "error": str(e)})
            console.print(f"[red]STOP[/red] {name}: {e}")
            return
        except Exception as e:  # parsing/schema errors: record and continue with other sources
            res.status = "partial"
            res.tasks.append({"task": name, "status": "error", "error": f"{type(e).__name__}: {e}"})
            console.print(f"[red]ERROR[/red] {name}: {e!r}")
            return
        state.mark(name, now)
        for t, n in added.items():
            res.rows_new[t] = res.rows_new.get(t, 0) + n
        res.tasks.append({"task": name, "status": "ok", "rows_new": added})
        console.print(f"[green]ok[/green] {name} {added}")

    def put(table: str, df: pd.DataFrame) -> dict[str, int]:
        return {table: store.write(warehouse, table, df)}

    # ---- event objects -----------------------------------------------------------------
    for ev in events:
        if not ev.intdes:
            continue
        d = ev.intdes
        task(
            f"gp_current:{d}",
            ct,
            cad["event_gp_current"],
            lambda d=d: put("gp_elements", celestrak_gp.fetch(ct, "INTDES", d, "current")[0]),
        )
        task(
            f"gp_first:{d}",
            ct,
            cad["event_gp_first"],
            lambda d=d: put("gp_elements", celestrak_gp.fetch(ct, "INTDES", d, "first")[0]),
        )
        task(
            f"satcat:{d}",
            ct,
            cad["event_satcat"],
            lambda d=d: put("satcat", celestrak_satcat.fetch(ct, "INTDES", d)[0]),
        )

    # ---- reentry inputs ----------------------------------------------------------------
    task(
        "gp_decaying",
        ct,
        cad["decaying_gp"],
        lambda: put("gp_elements", celestrak_gp.fetch(ct, "SPECIAL", "DECAYING", "current")[0]),
    )
    task("satcat_full", ct, cad["satcat_full"], lambda: put("satcat", celestrak_satcat.fetch_full(ct)[0]))

    def space_weather() -> dict[str, int]:
        have = (warehouse / "space_weather").exists()
        df, _ = celestrak_sw.fetch(ct, full=not have, ttl_s=cad["space_weather"])
        return put("space_weather", df)

    task("space_weather", ct, cad["space_weather"], space_weather)
    task("reentry_backfill", ct, cad["reentry_backfill"], lambda: _backfill(ct, warehouse, state, now, cfg))

    # ---- other hosts ------------------------------------------------------------------
    def live_sw() -> dict[str, int]:
        kp, f107 = swpc.fetch(noaa)
        return {**put("kp_live", kp), **put("f107_live", f107)}

    task("swpc", noaa, cad["swpc"], live_sw)

    def gcat_task() -> dict[str, int]:
        objects, launches, release = gcat.fetch(gc)
        state.data["gcat_release"] = release
        return {**put("gcat_objects", objects), **put("gcat_launches", launches)}

    task("gcat", gc, cad["gcat"], gcat_task)

    # ---- bookkeeping --------------------------------------------------------------------
    res.network_calls = sum(c.network_calls() for c in clients.values())
    log_rows = []
    seq = 0
    for host, c in clients.items():
        for rec in c.records():
            log_rows.append({"run_id": res.run_id, "seq": seq, "host": host, **rec})
            seq += 1
    if log_rows:
        log = pd.DataFrame(log_rows)
        log["started_at"] = pd.to_datetime(log["started_at"], utc=True)
        log["status"] = log["status"].astype("Int64")
        log["error"] = log["error"].astype("string")
        store.write(warehouse, "ingest_log", log)
    runs = state.data.setdefault("runs", [])
    runs.append({k: v for k, v in res.as_dict().items() if k != "tasks"})
    state.data["runs"] = runs[-60:]
    state.data["last_run"] = res.as_dict()
    state.save()
    for c in clients.values():
        c.close()
    return res


def _backfill(ct: PoliteClient, warehouse: Path, state: State, now: datetime, cfg: dict) -> dict[str, int]:
    """Fetch last-GP and first-GP for a few recently-decayed launches (reentry training set)."""
    bf = cfg["reentry_backfill"]
    sat = store.read(warehouse, "satcat")
    if sat.empty:
        return {}
    latest = sat.sort_values("fetched_at").drop_duplicates("norad_cat_id", keep="last")
    decay = pd.to_datetime(latest["decay_date"], errors="coerce", utc=True)
    m = (decay >= now - timedelta(days=bf["lookback_days"])) & latest["object_type"].isin(bf["object_types"])
    cand = latest[m].copy()
    cand["intdes"] = cand["object_id"].str.slice(0, 8)
    queue = cand.groupby("intdes").size().sort_values(ascending=False)
    done = set(state.data["backfill_done"])
    today = now.strftime("%Y-%m-%d")
    daily = state.data.setdefault("backfill_requests", {})
    for k in [k for k in daily if k != today]:
        del daily[k]
    room = (bf["max_requests_per_day"] - daily.get(today, 0)) // 2
    todo = [d for d in queue.index if d not in done][: max(0, min(bf["intdes_per_run"], room))]
    added = 0
    for d in todo:
        for kind in ("last", "first"):
            df, f = celestrak_gp.fetch(ct, "INTDES", d, kind)
            if not f.from_cache:
                daily[today] = daily.get(today, 0) + 1
            added += store.write(warehouse, "gp_elements", df)
        state.data["backfill_done"].append(d)
    state.data["backfill_remaining"] = int(len([d for d in queue.index if d not in set(state.data["backfill_done"])]))
    return {"gp_elements": added}
