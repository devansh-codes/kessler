from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kessler import config
from kessler.http import PoliteClient
from kessler.ingest import run_ingest
from kessler.warehouse import store
from tests.conftest import Router, fixture_text


def _routes(status: int = 200):
    ok = lambda name: (status, fixture_text(name))  # noqa: E731
    return {
        "gp-first.php?INTDES=1988-078": ok("gp_first_1988-078.csv"),
        "gp.php?INTDES=1988-078": ok("gp_current_1988-078.csv"),
        "gp-last.php": (status, fixture_text("gp_empty.txt")),
        "SPECIAL=DECAYING": ok("gp_current_2026-195.csv"),
        "records.php?INTDES=1988-078": ok("satcat_1988-078.csv"),
        "pub/satcat.csv": ok("satcat_1988-078.csv"),
        "SW-All.csv": ok("sw_sample.csv"),
        "SW-Last5Years.csv": ok("sw_sample.csv"),
        "noaa-planetary-k-index": (200, fixture_text("noaa_kp.json")),
        "f107_cm_flux": (200, fixture_text("noaa_f107.json")),
        "satcat100k.tsv": (200, fixture_text("gcat_satcat100k_sample.tsv")),
        "cat/satcat.tsv": (200, fixture_text("gcat_satcat_sample.tsv")),
        "launch.tsv": (200, fixture_text("gcat_launch_sample.tsv")),
    }


def _clients(tmp_path, router, clock):
    return {
        h: PoliteClient(tmp_path / "cache" / h, transport=router.transport(), now=clock)
        for h in ("celestrak", "noaa", "gcat")
    }


def _events():
    return [e for e in config.load_events() if e.id == "usa-32"]


def test_second_run_within_two_hours_makes_zero_calls(tmp_path):
    router = Router(_routes())
    t0 = datetime(2026, 10, 20, 6, 23, tzinfo=UTC)
    clock = lambda: t0.timestamp()  # noqa: E731
    r1 = run_ingest(tmp_path / "wh", tmp_path, now=t0, clients=_clients(tmp_path, router, clock), events=_events())
    assert r1.status == "ok", r1.tasks
    assert r1.network_calls > 0
    n = len(router.calls)
    t1 = t0 + timedelta(minutes=30)
    r2 = run_ingest(tmp_path / "wh", tmp_path, now=t1, clients=_clients(tmp_path, router, clock), events=_events())
    assert r2.network_calls == 0 and len(router.calls) == n
    log = store.read(tmp_path / "wh", "ingest_log")
    assert {"run_id", "url", "status", "bytes", "duration_ms"} <= set(log.columns)


def test_403_stops_celestrak_after_one_request(tmp_path):
    routes = {k: v for k, v in _routes().items()}
    for k in list(routes):
        if "noaa" not in k and "f107" not in k and ".tsv" not in k:
            routes[k] = (403, "Forbidden")
    router = Router(routes)
    t0 = datetime(2026, 10, 20, tzinfo=UTC)
    res = run_ingest(
        tmp_path / "wh", tmp_path, now=t0, clients=_clients(tmp_path, router, lambda: t0.timestamp()), events=_events()
    )
    celestrak_calls = [u for u in router.calls if "celestrak.org" in u]
    assert len(celestrak_calls) == 1
    assert res.status == "partial"
    # other hosts still ingest
    assert any("swpc" in u for u in router.calls)
