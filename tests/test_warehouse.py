from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd

from kessler.http import Fetched
from kessler.sources import celestrak_gp
from kessler.warehouse import store
from kessler.warehouse.db import connect
from tests.conftest import fixture_text


def _gp(name: str, kind: str) -> pd.DataFrame:
    f = Fetched("u", "", 200, False, datetime(2026, 10, 20, tzinfo=UTC))
    return celestrak_gp.annotate(celestrak_gp.parse_gp_csv(fixture_text(name)), f, f"{kind}:x", kind)


def test_append_dedupe_is_idempotent(tmp_path):
    df = _gp("gp_first_1988-078.csv", "first")
    assert store.write(tmp_path, "gp_elements", df) == len(df)
    assert store.write(tmp_path, "gp_elements", df) == 0
    assert len(store.read(tmp_path, "gp_elements")) == len(df)
    assert (tmp_path / "_SCHEMA_VERSION").exists()


def test_flags_are_merged_across_queries(tmp_path):
    first = _gp("gp_first_1988-078.csv", "first")
    current = _gp("gp_current_1988-078.csv", "current")
    store.write(tmp_path, "gp_elements", first)
    store.write(tmp_path, "gp_elements", current)
    out = store.read(tmp_path, "gp_elements")
    # 101040's first GP is also its current GP -> one row, flagged first
    r = out[out["norad_cat_id"] == 101040]
    assert len(r) == 1 and bool(r["is_first_gp"].iloc[0])
    assert not out.duplicated(["norad_cat_id", "epoch"]).any()


def test_partitions_are_hive_layout(tmp_path):
    store.write(tmp_path, "gp_elements", _gp("gp_first_1981-043.csv", "first"))
    dirs = {p.parent.relative_to(tmp_path / "gp_elements").as_posix() for p in tmp_path.rglob("*.parquet")}
    assert "year=1981/month=05" in dirs and "year=2024/month=05" in dirs


def test_six_digit_norad_round_trip_csv_parquet_duckdb_json(tmp_path):
    store.write(tmp_path, "gp_elements", _gp("gp_current_2026-195.csv", "current"))
    con = connect(tmp_path)
    row = con.execute(
        "SELECT norad_cat_id, typeof(norad_cat_id) FROM gp_latest WHERE norad_cat_id = 100472"
    ).fetchone()
    assert row == (100472, "BIGINT")
    payload = json.loads(json.dumps({"norad": int(row[0])}))
    assert payload["norad"] == 100472


def test_keep_last_policy_for_space_weather(tmp_path):
    a = pd.DataFrame({"date": pd.to_datetime(["2026-10-20"], utc=True), "f107_obs": [100.0],
                      "fetched_at": pd.to_datetime(["2026-10-19"], utc=True)})
    b = a.assign(f107_obs=[120.0], fetched_at=pd.to_datetime(["2026-10-21"], utc=True))
    store.write(tmp_path, "space_weather", a)
    store.write(tmp_path, "space_weather", b)
    assert store.read(tmp_path, "space_weather")["f107_obs"].tolist() == [120.0]
