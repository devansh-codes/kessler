from __future__ import annotations

import pandas as pd
import pytest

from kessler.sources import celestrak_gp, celestrak_satcat, celestrak_sw, gcat, swpc
from tests.conftest import fixture_text


def test_gp_csv_six_digit_norad_ids():
    df = celestrak_gp.parse_gp_csv(fixture_text("gp_first_1988-078.csv"))
    assert df["norad_cat_id"].dtype == "int64"
    assert 101049 in set(df["norad_cat_id"])
    assert df["epoch"].dt.tz is not None
    assert {"mean_motion", "bstar", "mean_motion_dot"} <= set(df.columns)


def test_gp_csv_rocket_body_100472():
    df = celestrak_gp.parse_gp_csv(fixture_text("gp_current_2026-195.csv"))
    rb = df[df["norad_cat_id"] == 100472]
    assert len(rb) == 1 and rb["object_name"].iloc[0] == "CZ-6C R/B"


def test_no_gp_data_found_is_empty_not_error():
    df = celestrak_gp.parse_gp_csv(fixture_text("gp_empty.txt"))
    assert df.empty and "norad_cat_id" in df.columns


def test_gp_schema_violation_raises():
    with pytest.raises(celestrak_gp.SchemaError):
        celestrak_gp.parse_gp_csv("OBJECT_NAME,NORAD_CAT_ID\nX,1\n")


def test_gp_urls_are_csv_and_never_tle():
    for kind in ("current", "first", "last"):
        u = celestrak_gp.gp_url("intdes", "1988-078", kind)
        assert u.startswith("https://celestrak.org/") and u.endswith("FORMAT=CSV")
        assert "TLE" not in u.upper().split("FORMAT=")[1]
    assert "gp-first.php" in celestrak_gp.gp_url("INTDES", "x", "first")
    assert "gp-last.php" in celestrak_gp.gp_url("INTDES", "x", "last")


def test_satcat_parse_decay_dates():
    df = celestrak_satcat.parse_satcat_csv(fixture_text("satcat_1988-078.csv"))
    row = df[df["norad_cat_id"] == 101037].iloc[0]
    assert row["decay_date"] == "2026-10-08" and row["object_type"] == "DEB"
    assert pd.isna(df[df["norad_cat_id"] == 19460]["decay_date"].iloc[0])


def test_space_weather_scaling():
    df = celestrak_sw.parse_sw_csv(fixture_text("sw_sample.csv"))
    storm = df[df["date"] == pd.Timestamp("2024-05-11", tz="UTC")].iloc[0]
    assert storm["kp_max"] == pytest.approx(9.0)  # Gannon storm, file stores Kp x10
    assert storm["f107_obs"] > 200
    assert {"f107_obs_center81", "ap_avg", "kp_sum"} <= set(df.columns)


def test_swpc_parsers():
    kp = swpc.parse_kp(fixture_text("noaa_kp.json"))
    assert len(kp) > 10 and kp["kp"].between(0, 9).all()
    f = swpc.parse_f107(fixture_text("noaa_f107.json"))
    assert f["flux"].between(50, 400).all()


def test_gcat_objects_and_launches():
    objs, upd = gcat.parse_objects(fixture_text("gcat_satcat100k_sample.tsv"))
    assert upd and upd.startswith("2026")
    deb = objs[objs["satcat"] == "101032"].iloc[0]
    assert deb["type_class"] == "D" and deb["parent"] == "S19460"
    assert objs["satcat_num"].max() >= 100472
    launches, _ = gcat.parse_launches(fixture_text("gcat_launch_sample.tsv"))
    assert launches.set_index("launch_tag").loc["2026-195", "lv_type"] == "Chang Zheng 6C"
