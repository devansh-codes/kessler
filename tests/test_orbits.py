from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import sgp4
from sgp4.api import Satrec
from sgp4.omm import _nddot_units, _ndot_units

from kessler.orbits import elements as E
from kessler.orbits.frames import (
    argument_of_latitude_deg,
    ecef_to_geodetic,
    gmst_rad,
    rtn_basis,
    to_rtn,
)
from kessler.orbits.propagate import propagate, satrec_from_row
from kessler.sources import celestrak_gp, celestrak_satcat
from tests.conftest import fixture_text

SGP4_DIR = Path(sgp4.__file__).parent


def _vallado_cases(limit: int = 12):
    """Yield (satrec_from_tle, [(tsince_min, x, y, z)]) from the files shipped with sgp4."""
    lines = (SGP4_DIR / "SGP4-VER.TLE").read_text().splitlines()
    tles = [(lines[i], lines[i + 1]) for i in range(len(lines) - 1) if lines[i].startswith("1 ") and lines[i + 1].startswith("2 ")]
    out = (SGP4_DIR / "tcppver.out").read_text().splitlines()
    expected: dict[str, list] = {}
    cur = None
    for ln in out:
        parts = ln.split()
        if not parts:
            continue
        if ln.rstrip().endswith("xx"):
            cur = parts[0]
            expected[cur] = []
        elif cur and len(parts) >= 4:
            try:
                expected[cur].append(tuple(float(p) for p in parts[:4]))
            except ValueError:
                pass
    n = 0
    for l1, l2 in tles:
        sat = Satrec.twoline2rv(l1, l2)
        key = l1[2:7].strip().lstrip("0")
        rows = expected.get(key) or expected.get(l1[2:7].strip())
        if not rows or sat.error:
            continue
        # skip deep-space and error cases: our OMM path is used for near-Earth objects
        if 2 * np.pi / sat.no_kozai >= 225:
            continue
        yield sat, rows
        n += 1
        if n >= limit:
            return


def test_omm_path_reproduces_vallado_verification_vectors():
    checked = 0
    for sat, rows in _vallado_cases():
        jd = sat.jdsatepoch + sat.jdsatepochF
        row = {
            "object_name": "TEST", "object_id": "", "classification_type": "U",
            "epoch": pd.Timestamp((jd - 2440587.5) * 86400, unit="s", tz="UTC"),
            "mean_motion": sat.no_kozai * 720.0 / np.pi, "eccentricity": sat.ecco,
            "inclination": np.degrees(sat.inclo), "ra_of_asc_node": np.degrees(sat.nodeo),
            "arg_of_pericenter": np.degrees(sat.argpo), "mean_anomaly": np.degrees(sat.mo),
            "ephemeris_type": 0, "norad_cat_id": sat.satnum, "element_set_no": 999, "rev_at_epoch": 0,
            "bstar": sat.bstar, "mean_motion_dot": sat.ndot * _ndot_units, "mean_motion_ddot": sat.nddot * _nddot_units,
        }
        ours = satrec_from_row(row)
        for tsince, x, y, z in rows[:5]:
            e, r, _ = ours.sgp4_tsince(tsince)
            if e != 0:
                continue
            # OMM epoch is microsecond-rounded and elements are exported in decimal: allow 5 m
            assert np.allclose(r, [x, y, z], atol=5e-3), (sat.satnum, tsince)
            checked += 1
    assert checked >= 20


def test_apogee_perigee_match_satcat_within_5km():
    gp = celestrak_gp.parse_gp_csv(fixture_text("gp_current_1981-043.csv"))
    sc = celestrak_satcat.parse_satcat_csv(fixture_text("satcat_1981-043.csv"))
    m = gp.merge(sc[["norad_cat_id", "apogee", "perigee"]], on="norad_cat_id").dropna(subset=["apogee"])
    assert len(m) >= 5
    apo = E.apogee_alt_km(m["mean_motion"], m["eccentricity"])
    peri = E.perigee_alt_km(m["mean_motion"], m["eccentricity"])
    # SATCAT values come from a slightly different element set; most agree to a few km
    good = (np.abs(apo - m["apogee"]) < 5) & (np.abs(peri - m["perigee"]) < 5)
    assert good.mean() >= 0.6


def test_reentry_threshold_mean_motion():
    assert E.mean_motion_for_altitude(180) == pytest.approx(16.35, abs=0.05)
    assert E.period_min(14.0) == pytest.approx(1440 / 14)


def test_six_digit_norad_propagates():
    gp = celestrak_gp.parse_gp_csv(fixture_text("gp_current_2026-195.csv"))
    rb = gp[gp["norad_cat_id"] == 100472]
    p = propagate(rb, [rb["epoch"].iloc[0], rb["epoch"].iloc[0] + pd.Timedelta(minutes=10)])
    assert p.ok.all()
    alt = np.linalg.norm(p.r[0], axis=-1) - E.R_EARTH
    assert ((alt > 300) & (alt < 600)).all()


def test_gmst_at_j2000():
    assert np.degrees(gmst_rad(2451545.0)) == pytest.approx(280.46061837, abs=1e-6)


def test_rtn_is_orthonormal_and_right_handed():
    rng = np.random.default_rng(1)
    r = rng.normal(size=(50, 3)) * 7000
    v = rng.normal(size=(50, 3)) * 7
    B = rtn_basis(r, v)
    eye = np.einsum("nij,nkj->nik", B, B)
    assert np.allclose(eye, np.eye(3), atol=1e-12)
    assert np.allclose(np.cross(B[:, 0], B[:, 1]), B[:, 2], atol=1e-12)
    # a radial vector has only an R component
    assert np.allclose(to_rtn(r, r, v)[:, 1:], 0, atol=1e-9)


def test_geodetic_equator_and_pole():
    lat, lon, h = ecef_to_geodetic(np.array([[6378.137 + 500, 0, 0], [0, 0, 6356.752 + 100]]))
    assert lat[0] == pytest.approx(0, abs=1e-9) and h[0] == pytest.approx(500, abs=1e-6)
    assert lat[1] == pytest.approx(90, abs=1e-6) and h[1] == pytest.approx(100, abs=1e-2)
    assert lon[0] == pytest.approx(0)


def test_argument_of_latitude():
    r = np.array([0.0, 7000, 0])
    v = np.array([0.0, 0, 7.5])  # polar orbit, node on +y axis
    assert argument_of_latitude_deg(r, v) == pytest.approx(0, abs=1e-9)
