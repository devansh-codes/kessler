"""Kessler command line: ingest | build | export | status | solve | forecast | resolve."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from kessler import __version__

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Kessler: orbital breakup forensics lab.")
console = Console()

WAREHOUSE = typer.Option(Path("warehouse"), "--warehouse", "-w", help="Parquet warehouse directory")
CACHE = typer.Option(Path(".cache/http"), "--cache", help="HTTP response cache directory")
BUILD = typer.Option(Path("build_out"), "--build-dir", help="Derived-table output directory")


@app.callback()
def _main(version: bool = typer.Option(False, "--version", help="Show version and exit")) -> None:
    if version:
        console.print(f"kessler {__version__}")
        raise typer.Exit()


@app.command()
def ingest(
    warehouse: Path = WAREHOUSE,
    cache: Path = CACHE,
    only: list[str] = typer.Option(None, "--only", help="Run only tasks whose name starts with this"),
    strict: bool = typer.Option(False, "--strict", help="Exit non-zero when any source failed"),
) -> None:
    """Fetch new data from CelesTrak / NOAA / GCAT into the Parquet warehouse (polite, cached)."""
    from kessler.ingest import run_ingest

    res = run_ingest(warehouse, cache, only=set(only) if only else None)
    console.print(f"run {res.run_id}: status={res.status} network_calls={res.network_calls} rows_new={res.rows_new}")
    if strict and res.status != "ok":
        raise typer.Exit(1)


@app.command()
def status(warehouse: Path = WAREHOUSE) -> None:
    """Show per-source freshness and row counts."""
    from kessler.warehouse.db import connect
    from kessler.warehouse.schema import TABLES

    state_path = warehouse / "_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    t = Table(title="Sources (last success)")
    t.add_column("task")
    t.add_column("last success (UTC)")
    for k, v in sorted(state.get("last_success", {}).items()):
        t.add_row(k, v)
    console.print(t)
    con = connect(warehouse)
    t2 = Table(title="Warehouse tables")
    t2.add_column("table")
    t2.add_column("rows", justify="right")
    for name in TABLES:
        try:
            n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        except Exception:
            n = 0
        t2.add_row(name, f"{n:,}")
    console.print(t2)
    last = state.get("last_run")
    if last:
        console.print(f"last run {last['run_id']} status={last['status']} network_calls={last['network_calls']}")


@app.command()
def resolve(cache: Path = CACHE) -> None:
    """Resolve name-only event parents through SATCAT and pin them in config/events.lock.json."""
    from kessler import config
    from kessler.http import PoliteClient
    from kessler.sources import celestrak_satcat

    client = PoliteClient(cache / "celestrak")
    pins = {}
    for ev in config.load_events():
        if ev.norad and ev.intdes:
            continue
        key, val = ("CATNR", ev.parent.norad) if ev.parent.norad else ("NAME", ev.parent.name)
        df, _ = celestrak_satcat.fetch(client, key, val)
        exact = df[df["object_name"] == (ev.parent.name or df["object_name"].iloc[0])]
        row = (exact if not exact.empty else df).iloc[0]
        pins[ev.id] = {
            "norad": int(row["norad_cat_id"]),
            "intdes": str(row["object_id"])[:8],
            "object_name": str(row["object_name"]),
        }
        console.print(f"{ev.id}: {pins[ev.id]}")
    if pins:
        config.save_lock(pins)


@app.command()
def build(warehouse: Path = WAREHOUSE, build_dir: Path = BUILD) -> None:
    """Compute derived tables (membership, breakup solutions, Δv, Gabbard, reentry, scorecard)."""
    from kessler.build import run_build

    run_build(warehouse, build_dir)


@app.command()
def export(
    out: Path = typer.Option(Path("site/public/data"), "--out"),
    warehouse: Path = WAREHOUSE,
    build_dir: Path = BUILD,
) -> None:
    """Write the static data products consumed by the website (fails if a size budget is exceeded)."""
    from kessler.export.products import run_export

    run_export(warehouse, build_dir, out)


@app.command()
def solve(event_id: str, warehouse: Path = WAREHOUSE) -> None:
    """Run the breakup solver for one event and print the solution."""
    from kessler.build import solve_event

    console.print_json(json.dumps(solve_event(warehouse, event_id), default=str))


@app.command()
def forecast(warehouse: Path = WAREHOUSE) -> None:
    """Train the reentry model and append live forecasts (with issued_at) to the warehouse."""
    from kessler.reentry.live import issue_forecasts

    n = issue_forecasts(warehouse)
    console.print(f"issued {n} forecasts")


if __name__ == "__main__":
    app()
