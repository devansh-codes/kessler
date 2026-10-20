"""Warehouse table specifications.

Every table is hive-partitioned Parquet under ``warehouse/<table>/``. A spec says how a table is
partitioned, which columns form its key and how duplicates on that key are resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = 1

OMM_COLUMNS = [
    "OBJECT_NAME",
    "OBJECT_ID",
    "EPOCH",
    "MEAN_MOTION",
    "ECCENTRICITY",
    "INCLINATION",
    "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER",
    "MEAN_ANOMALY",
    "EPHEMERIS_TYPE",
    "CLASSIFICATION_TYPE",
    "NORAD_CAT_ID",
    "ELEMENT_SET_NO",
    "REV_AT_EPOCH",
    "BSTAR",
    "MEAN_MOTION_DOT",
    "MEAN_MOTION_DDOT",
]

SATCAT_COLUMNS = [
    "OBJECT_NAME",
    "OBJECT_ID",
    "NORAD_CAT_ID",
    "OBJECT_TYPE",
    "OPS_STATUS_CODE",
    "OWNER",
    "LAUNCH_DATE",
    "LAUNCH_SITE",
    "DECAY_DATE",
    "PERIOD",
    "INCLINATION",
    "APOGEE",
    "PERIGEE",
    "RCS",
    "DATA_STATUS_CODE",
    "ORBIT_CENTER",
    "ORBIT_TYPE",
]


@dataclass(frozen=True)
class TableSpec:
    name: str
    key: tuple[str, ...]
    # column holding a timestamp/date used for partitioning; None = single unpartitioned file
    partition_col: str | None = None
    # "month" -> year=/month=, "year" -> year=
    granularity: str = "month"
    # boolean columns OR-ed across duplicates (e.g. is_first_gp seen from two queries)
    or_flags: tuple[str, ...] = field(default_factory=tuple)
    # when True the table is replaced on each write instead of merged
    replace: bool = False
    # which duplicate survives (ordered by fetched_at): "first" keeps history stable,
    # "last" lets newer data win (space weather predictions -> observations)
    keep: str = "first"


TABLES: dict[str, TableSpec] = {
    "gp_elements": TableSpec(
        "gp_elements", ("norad_cat_id", "epoch"), "epoch", "month", or_flags=("is_first_gp", "is_last_gp")
    ),
    # SATCAT is stored as change records: a new row only when an identity/status field changes.
    "satcat": TableSpec(
        "satcat",
        ("norad_cat_id", "object_type", "ops_status_code", "decay_date", "object_name"),
        "fetched_at",
        "year",
    ),
    "space_weather": TableSpec("space_weather", ("date",), "date", "year", keep="last"),
    "kp_live": TableSpec("kp_live", ("time_tag",), "time_tag", "month"),
    "f107_live": TableSpec("f107_live", ("time_tag",), "time_tag", "year", keep="last"),
    "gcat_objects": TableSpec("gcat_objects", ("jcat",), replace=True),
    "gcat_launches": TableSpec("gcat_launches", ("launch_tag",), replace=True),
    "ingest_log": TableSpec("ingest_log", ("run_id", "seq"), "started_at", "month"),
    "reentry_forecasts": TableSpec("reentry_forecasts", ("norad_cat_id", "issued_at"), "issued_at", "month"),
}

GP_VIEWS_SQL = """
CREATE OR REPLACE VIEW gp_latest AS
  SELECT * EXCLUDE (rn) FROM (
    SELECT *, row_number() OVER (PARTITION BY norad_cat_id ORDER BY epoch DESC) AS rn FROM gp_elements
  ) WHERE rn = 1;
CREATE OR REPLACE VIEW gp_first AS
  SELECT * EXCLUDE (rn) FROM (
    SELECT *, row_number() OVER (PARTITION BY norad_cat_id ORDER BY epoch ASC) AS rn FROM gp_elements
  ) WHERE rn = 1;
"""

SATCAT_VIEWS_SQL = """
CREATE OR REPLACE VIEW satcat_latest AS
  SELECT * EXCLUDE (rn) FROM (
    SELECT *, row_number() OVER (PARTITION BY norad_cat_id ORDER BY fetched_at DESC) AS rn FROM satcat
  ) WHERE rn = 1;
"""
