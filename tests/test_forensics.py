from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from kessler.forensics import deltav, epoch_solver, membership, parent_only
from kessler.forensics.synthetic import make_breakup
from kessler.sources import celestrak_gp, celestrak_satcat
from tests.conftest import fixture_text


@pytest.fixture(scope="module")
def parent() -> pd.Series:
    gp = celestrak_gp.parse_gp_csv(fixture_text("gp_current_1988-078.csv"))
    return gp[gp["norad_cat_id"] == 19460].iloc[0]


@pytest.fixture(scope="module")
def synthetic(parent):
    t_break = pd.Timestamp("2026-10-15T03:17:00Z")
    p, frags, dv_true = make_breakup(parent, t_break, n=25, sigma_ms=20, catalogue_after_days=2, seed=3)
    return t_break, p, frags, dv_true


def test_synthetic_breakup_time_recovered_within_2_minutes(synthetic):
    t_break, p, frags, _ = synthetic
    ref = t_break + pd.Timedelta(minutes=40)  # a "reported" time that is slightly off
    sol = epoch_solver.solve(p, frags, ref, method="hybrid", n_boot=50)
    err_min = abs((sol.t_p50 - t_break).total_seconds()) / 60
    assert err_min < 2.0, f"t* off by {err_min:.2f} min"
    assert sol.t_p05 <= sol.t_p50 <= sol.t_p95
    assert sol.lat is not None and -90 <= sol.lat <= 90


def test_synthetic_dv_median_within_20_percent(synthetic):
    t_break, p, frags, dv_true = synthetic
    sol = epoch_solver.solve(p, frags, t_break, method="hybrid", n_boot=0)
    dv = deltav.fragment_dv(p, frags, sol.t_p50)
    true_med = np.median(np.linalg.norm(dv_true, axis=1))
    est_med = dv.loc[dv["reliable"], "dv_mag"].median()
    assert abs(est_med - true_med) / true_med < 0.2, (est_med, true_med)
    stats = deltav.dv_stats(dv[dv["reliable"]])
    assert stats["n"] >= 20 and stats["p90_ms"] >= stats["median_ms"]


def test_no_fragments_flags(parent):
    sol = epoch_solver.solve(parent, parent.to_frame().T.iloc[0:0], pd.Timestamp("2026-10-01T00:00Z"))
    assert "NO_PUBLIC_FRAGMENTS" in sol.flags and sol.t_p50 is None


def test_membership_separates_old_debris_meteor():
    gp = pd.concat(
        [
            celestrak_gp.parse_gp_csv(fixture_text("gp_first_1981-043.csv")),
            celestrak_gp.parse_gp_csv(fixture_text("gp_current_1981-043.csv")),
        ]
    )
    sc = celestrak_satcat.parse_satcat_csv(fixture_text("satcat_1981-043.csv"))
    cands, summary = membership.assign_members(12456, "1981-043", pd.Timestamp("2026-10-05T09:45Z"), gp, sc)
    assert summary["counts"]["members"] == 0  # no 2026 debris public in the fixture
    assert summary["counts"]["decayed_before_event"] >= 5
    assert (cands["assignment_method"].str.startswith("excluded")).all()
    # old debris planes are spread far from the parent's plane
    alive = cands.dropna(subset=["plane_angle_deg"])
    assert (alive["plane_angle_deg"] > 3).mean() > 0.5


def test_membership_usa32_fragments_counted():
    gp = pd.concat(
        [
            celestrak_gp.parse_gp_csv(fixture_text("gp_first_1988-078.csv")),
            celestrak_gp.parse_gp_csv(fixture_text("gp_current_1988-078.csv")),
        ]
    )
    sc = celestrak_satcat.parse_satcat_csv(fixture_text("satcat_1988-078.csv"))
    cands, summary = membership.assign_members(19460, "1988-078", pd.Timestamp("2026-09-13T21:13Z"), gp, sc, eps_deg=3.0)
    assert summary["counts"]["intdes_candidates"] == 18
    assert summary["counts"]["members"] >= 15
    assert cands["norad_cat_id"].max() == 101049


def test_parent_only_changepoint_and_dv():
    t = pd.date_range("2026-09-01", periods=12, freq="12h", tz="UTC")
    n = np.r_[np.full(6, 14.34), np.full(6, 14.345)]
    s = pd.DataFrame({"epoch": t, "mean_motion": n, "eccentricity": 0.0005, "bstar": 1e-4})
    out = parent_only.analyse(s, pd.Timestamp("2026-09-03T20:00Z"))
    assert out["changepoints"], out
    assert out["dv_t_ms"] is not None and out["dv_t_ms"] < 0  # higher mean motion = lower orbit
    short = parent_only.analyse(s.head(2), pd.Timestamp("2026-09-01T06:00Z"))
    assert "INSUFFICIENT_HISTORY" in short["flags"]
