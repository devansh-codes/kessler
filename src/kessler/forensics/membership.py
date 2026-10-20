"""Which catalogued objects belong to an event (plan §7.4).

1. Candidates: debris (DEB/UNK) sharing the parent's international designator.
2. Time filter: first catalogued no earlier than one day before the reference time.
3. Orbital clustering: propagate every candidate still in orbit to the reference epoch and run DBSCAN
   on the angle between orbit planes. Fresh debris shares the parent's plane; decades-old debris has
   precessed away (Meteor 2-7's 2004 cloud). Members must pass the time filter and must not sit in a
   cluster that excludes the parent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

from kessler.orbits.propagate import propagate

DEBRIS_TYPES = {"DEB", "UNK"}


def _plane_normal(r: np.ndarray, v: np.ndarray) -> np.ndarray:
    h = np.cross(r, v)
    return h / np.linalg.norm(h, axis=-1, keepdims=True)


def _raan_inc(nhat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    inc = np.degrees(np.arccos(np.clip(nhat[:, 2], -1, 1)))
    raan = np.degrees(np.arctan2(nhat[:, 0], -nhat[:, 1])) % 360
    return raan, inc


def assign_members(
    parent_norad: int,
    intdes: str,
    ref_time: pd.Timestamp,
    gp: pd.DataFrame,
    satcat: pd.DataFrame,
    eps_deg: float = 1.5,
    min_samples: int = 2,
) -> tuple[pd.DataFrame, dict]:
    """Return (per-candidate table, summary). ``gp`` holds all element sets for this designator."""
    ref_time = pd.Timestamp(ref_time)
    gp = gp.reset_index(drop=True)
    sc = satcat[satcat["object_id"].fillna("").str.startswith(intdes)].drop_duplicates("norad_cat_id", keep="last")
    cands = sc[(sc["norad_cat_id"] != parent_norad) & sc["object_type"].isin(DEBRIS_TYPES)].copy()
    # objects with GP data but not (yet) in our SATCAT snapshot
    extra = set(gp.loc[gp["object_name"].fillna("").str.contains("DEB"), "norad_cat_id"]) - set(cands["norad_cat_id"]) - {parent_norad}
    if extra:
        names = gp[gp["norad_cat_id"].isin(extra)].drop_duplicates("norad_cat_id")[["norad_cat_id", "object_name", "object_id"]]
        cands = pd.concat([cands, names.assign(object_type="DEB")], ignore_index=True)
    first = gp.groupby("norad_cat_id")["epoch"].min().rename("first_epoch")
    cands = cands.merge(first, left_on="norad_cat_id", right_index=True, how="left")
    decay = pd.to_datetime(cands.get("decay_date"), errors="coerce", utc=True)
    cands["decayed_before_ref"] = decay < ref_time - pd.Timedelta(days=1)
    cands["passes_time"] = cands["first_epoch"] >= ref_time - pd.Timedelta(days=1)

    # --- clustering at a common epoch ---------------------------------------------------------
    # Use the epoch at which the new debris was first catalogued (median), not the reference time:
    # back-propagating high-drag fragments by weeks moves their planes by degrees (SGP4 drag error).
    # Old debris clouds (e.g. Meteor 2-7's 2004 pieces) are spread in RAAN at any recent epoch.
    alive = cands[~cands["decayed_before_ref"] & cands["first_epoch"].notna()]
    fresh = alive[alive["passes_time"]]
    common = pd.Timestamp(fresh["first_epoch"].median()) if len(fresh) else max(ref_time, gp["epoch"].max())
    pick = []
    for norad in [parent_norad, *alive["norad_cat_id"].tolist()]:
        g = gp[gp["norad_cat_id"] == norad]
        if g.empty:
            continue
        i = (g["epoch"] - common).abs().idxmin()
        pick.append(g.loc[i])
    cluster = pd.DataFrame(columns=["norad_cat_id", "cluster_label", "raan", "inc", "plane_angle_deg"])
    if len(pick) >= 2:
        rows = pd.DataFrame(pick).reset_index(drop=True)
        p = propagate(rows, [common])
        r, v = p.r[:, 0, :], p.v[:, 0, :]
        ok = np.all(np.isfinite(r), axis=1)
        rows, r, v = rows[ok].reset_index(drop=True), r[ok], v[ok]
        if len(rows) >= 2 and rows["norad_cat_id"].iloc[0] == parent_norad:
            nhat = _plane_normal(r, v)
            cosang = np.clip(nhat @ nhat.T, -1, 1)
            dist = np.degrees(np.arccos(cosang))
            labels = DBSCAN(eps=eps_deg, min_samples=min_samples, metric="precomputed").fit_predict(dist)
            raan, inc = _raan_inc(nhat)
            cluster = pd.DataFrame(
                {
                    "norad_cat_id": rows["norad_cat_id"].astype("int64"),
                    "cluster_label": labels,
                    "raan": raan,
                    "inc": inc,
                    "plane_angle_deg": dist[0],
                }
            )
    parent_label = int(cluster.loc[cluster["norad_cat_id"] == parent_norad, "cluster_label"].iloc[0]) if len(cluster) else -1
    cands = cands.merge(cluster, on="norad_cat_id", how="left")

    def decide(row) -> tuple[bool, str]:
        if row["decayed_before_ref"]:
            return False, "excluded: decayed before the event"
        if not row["passes_time"]:
            return False, "excluded: catalogued before the event"
        lab = row.get("cluster_label")
        if pd.notna(lab) and parent_label != -1 and int(lab) not in (parent_label, -1):
            return False, "excluded: different orbital-plane cluster"
        if pd.notna(lab) and parent_label != -1 and int(lab) == parent_label:
            return True, "cluster"
        return True, "time"

    decided = cands.apply(decide, axis=1, result_type="expand") if len(cands) else pd.DataFrame(columns=[0, 1])
    cands["in_event"] = decided[0].astype(bool) if len(cands) else []
    cands["assignment_method"] = decided[1] if len(cands) else []

    # parent row for the explainer plot
    prow = cluster[cluster["norad_cat_id"] == parent_norad]
    counts = {
        "intdes_candidates": int(len(cands)),
        "pass_time_filter": int(cands["passes_time"].sum()) if len(cands) else 0,
        "decayed_before_event": int(cands["decayed_before_ref"].sum()) if len(cands) else 0,
        "cluster_confirmed": int((cands["assignment_method"] == "cluster").sum()) if len(cands) else 0,
        "members": int(cands["in_event"].sum()) if len(cands) else 0,
    }
    summary = {
        "counts": counts,
        "parent_label": parent_label,
        "parent_plane": None if prow.empty else {"raan": float(prow["raan"].iloc[0]), "inc": float(prow["inc"].iloc[0])},
        "cluster_epoch": common.isoformat(),
    }
    return cands.reset_index(drop=True), summary
