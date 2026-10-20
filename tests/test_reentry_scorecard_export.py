from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from kessler.export import products
from kessler.export.ephem import build_ephemeris, rk4_j2
from kessler.reentry.baseline import N_CRIT, baseline_days
from kessler.reentry.dataset import FEATURES
from kessler.reentry.evaluate import backtest
from kessler.reentry.model import QuantileModel
from kessler.scorecard.gcat_stats import compute, family
from kessler.sources import celestrak_gp, gcat
from tests.conftest import fixture_text


def test_baseline_formula_and_guards():
    # n = 16.0 rev/d, MEAN_MOTION_DOT = 0.01 (half the derivative) -> (16.35 - 16) / 0.02 days
    assert baseline_days(16.0, 0.01) == pytest.approx((N_CRIT - 16.0) / 0.02)
    assert baseline_days(15.0, -1e-5) == 365.0  # non-decaying -> capped
    assert baseline_days(17.0, 0.01) == 0.01  # already below threshold -> floor


def _synthetic_frame(n=900, seed=0):
    rng = np.random.default_rng(seed)
    perigee = rng.uniform(150, 450, n)
    days = np.exp(0.018 * (perigee - 150) + rng.normal(0, 0.35, n))
    df = pd.DataFrame({f: rng.normal(size=n) for f in FEATURES})
    df["perigee_km"] = perigee
    df["log_baseline_days"] = np.log(days) + rng.normal(0, 0.8, n)
    df["days_to_decay"] = days
    df["baseline_days"] = np.exp(df["log_baseline_days"])
    df["epoch"] = pd.date_range("2025-01-01", periods=n, freq="6h", tz="UTC")
    df["decay_ts"] = df["epoch"] + pd.to_timedelta(days, unit="D")
    df["norad_cat_id"] = rng.integers(0, 200, n)
    return df


def test_conformal_coverage_close_to_nominal():
    df = _synthetic_frame()
    tr, cal, te = df.iloc[:500], df.iloc[500:700], df.iloc[700:]
    m = QuantileModel().fit(tr, tr["days_to_decay"].to_numpy())
    m.calibrate(cal, cal["days_to_decay"].to_numpy())
    lo, hi = m.interval(te, 0.8)
    y = te["days_to_decay"].to_numpy()
    cov = ((y >= lo) & (y <= hi)).mean()
    assert 0.68 <= cov <= 0.92
    assert (lo <= m.median(te)).all() and (m.median(te) <= hi).all()


def test_backtest_reports_metrics_and_beats_noisy_baseline():
    bt, model = backtest(_synthetic_frame(1200))
    names = [m["model"] for m in bt["metrics"]]
    assert "Physics baseline" in names and model is not None
    mdl = next(m for m in bt["metrics"] if m["model"].startswith("Quantile GBM +"))
    base = next(m for m in bt["metrics"] if m["model"] == "Physics baseline")
    assert mdl["mae_days"] < base["mae_days"]
    assert {c["nominal"] for c in bt["calibration"]} == {0.5, 0.8, 0.9}


def test_backtest_needs_enough_rows():
    bt, model = backtest(_synthetic_frame(50))
    assert model is None and bt["notes"]


def test_vehicle_families():
    assert family("Chang Zheng 6A") == "Long March 6A"
    assert family("Chang Zheng 6C") == "Long March 6C"
    assert family("Falcon 9") == "Falcon 9"
    assert family("Delta 7925") == "Delta II"
    assert family("Atlas V 551") == "Atlas V"
    assert family("Soyuz-2-1B") == "Soyuz-2"
    assert family(None) == "Unknown"


def test_scorecard_counts_stage_debris():
    objs, _ = gcat.parse_objects(fixture_text("gcat_satcat_sample.tsv"))
    launches, _ = gcat.parse_launches(fixture_text("gcat_launch_sample.tsv"))
    objs = pd.concat([objs, objs.assign(jcat="S00118", type="R2", type_class="R", name="Ablestar", parent="-")]).drop_duplicates("jcat", keep="last")
    g, events = compute(objs, launches)
    assert isinstance(g, pd.DataFrame) and "debris_per_launch" in g.columns


def test_export_budget_fails(tmp_path, monkeypatch):
    big = tmp_path / "events" / "x"
    big.mkdir(parents=True)
    (big / "ephem.bin").write_bytes(b"\0" * 2000)
    monkeypatch.setattr(products.config, "settings", lambda: {"export": {"ephem_max_bytes": 1000, "total_max_bytes": 10**9}})
    with pytest.raises(products.BudgetExceeded):
        products.check_budgets(tmp_path)


def test_rk4_j2_conserves_energy_roughly():
    r0 = np.array([[7000.0, 0, 0]])
    v0 = np.array([[0, 7.546, 0.5]])
    out = rk4_j2(r0, v0, np.array([0.0, 3000.0, 6000.0]))
    rn = np.linalg.norm(out[0], axis=1)
    assert np.all(np.abs(rn - 7000) < 200)


def test_ephemeris_shape_and_decay_mask():
    gp = celestrak_gp.parse_gp_csv(fixture_text("gp_current_1988-078.csv"))
    t0 = pd.Timestamp("2026-10-15T00:00Z")
    objs = pd.DataFrame({"norad_cat_id": [19460, 101032], "name": ["USA 32", "DEB"]})
    arr, meta = build_ephemeris(t0, objs, gp, 19460, None, {101032: pd.Timestamp("2026-10-16", tz="UTC")}, dense_hours=1, dense_step_s=600, daily_days=5, now=pd.Timestamp("2026-10-25T00:00Z"))
    assert arr.dtype == np.dtype("<f4") and arr.shape == (meta["T"], meta["N"], 3)
    assert meta["norads"] == [19460, 101032] and meta["parent_index"] == 0
    after = np.array(meta["times"]) > meta["decay_s"][1]
    assert np.isnan(arr[after, 1, 0]).all()
    assert np.isfinite(arr[:, 0, 0]).all()
    lat = arr[..., 0][np.isfinite(arr[..., 0])]
    assert (np.abs(lat) <= 90).all()
