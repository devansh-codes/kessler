"""Vectorised SGP4 propagation of OMM element sets (SatrecArray), TEME output."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sgp4.api import Satrec, SatrecArray
from sgp4.omm import initialize

from kessler.orbits.frames import teme_to_geodetic

OMM_KEYS = {
    "object_name": "OBJECT_NAME",
    "object_id": "OBJECT_ID",
    "epoch": "EPOCH",
    "mean_motion": "MEAN_MOTION",
    "eccentricity": "ECCENTRICITY",
    "inclination": "INCLINATION",
    "ra_of_asc_node": "RA_OF_ASC_NODE",
    "arg_of_pericenter": "ARG_OF_PERICENTER",
    "mean_anomaly": "MEAN_ANOMALY",
    "ephemeris_type": "EPHEMERIS_TYPE",
    "classification_type": "CLASSIFICATION_TYPE",
    "norad_cat_id": "NORAD_CAT_ID",
    "element_set_no": "ELEMENT_SET_NO",
    "rev_at_epoch": "REV_AT_EPOCH",
    "bstar": "BSTAR",
    "mean_motion_dot": "MEAN_MOTION_DOT",
    "mean_motion_ddot": "MEAN_MOTION_DDOT",
}


def _omm_fields(row) -> dict[str, str]:
    f = {}
    for low, up in OMM_KEYS.items():
        v = row[low]
        if low == "epoch":
            v = pd.Timestamp(v).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S.%f")
        elif v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
            v = "0" if low not in ("object_name", "object_id", "classification_type") else ""
        f[up] = str(v)
    if not f["CLASSIFICATION_TYPE"]:
        f["CLASSIFICATION_TYPE"] = "U"
    return f


def satrec_from_row(row) -> Satrec:
    s = Satrec()
    initialize(s, _omm_fields(row))
    return s


def to_jd(times) -> tuple[np.ndarray, np.ndarray]:
    """UTC datetimes -> (jd whole, fraction) arrays. SGP4 uses UTC as its time argument."""
    ts = pd.to_datetime(pd.Series(times), utc=True).dt.as_unit("ns")
    ns = ts.astype("int64").to_numpy()
    days = ns / 86_400e9
    jd = np.floor(days) + 2440587.5
    fr = days - np.floor(days)
    return jd, fr


@dataclass
class Propagated:
    r: np.ndarray  # (n_obj, n_t, 3) km TEME
    v: np.ndarray  # (n_obj, n_t, 3) km/s TEME
    err: np.ndarray  # (n_obj, n_t) sgp4 error codes (0 = ok)
    jd: np.ndarray
    fr: np.ndarray

    @property
    def ok(self) -> np.ndarray:
        return self.err == 0


def propagate(rows: pd.DataFrame, times) -> Propagated:
    sats = [satrec_from_row(r) for r in rows.to_dict("records")]
    jd, fr = to_jd(times)
    if not sats:
        z = np.zeros((0, len(jd), 3))
        return Propagated(z, z, np.zeros((0, len(jd)), dtype=int), jd, fr)
    e, r, v = SatrecArray(sats).sgp4(jd, fr)
    r = np.where(e[..., None] == 0, r, np.nan)
    v = np.where(e[..., None] == 0, v, np.nan)
    return Propagated(r, v, e, jd, fr)


def geodetic_tracks(rows: pd.DataFrame, times) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(lat, lon, alt) arrays of shape (n_obj, n_t)."""
    p = propagate(rows, times)
    lat, lon, alt = teme_to_geodetic(p.r, (p.jd + p.fr)[None, :])
    return lat, lon, alt


def time_grid(start, end, step_s: float) -> pd.DatetimeIndex:
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start.tz is None:
        start, end = start.tz_localize("UTC"), end.tz_localize("UTC")
    return pd.date_range(start, end, freq=pd.Timedelta(seconds=step_s))
