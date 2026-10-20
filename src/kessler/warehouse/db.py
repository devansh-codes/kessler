"""DuckDB connection factory: in-memory views over the Parquet warehouse (no server)."""

from __future__ import annotations

from pathlib import Path

import duckdb

from kessler.warehouse.schema import GP_VIEWS_SQL, SATCAT_VIEWS_SQL, TABLES


def connect(warehouse_dir: Path) -> duckdb.DuckDBPyConnection:
    warehouse_dir = Path(warehouse_dir).resolve()
    con = duckdb.connect(":memory:")
    present = []
    for table in TABLES:
        if any((warehouse_dir / table).rglob("part-*.parquet")):
            glob = (warehouse_dir / table / "**" / "*.parquet").as_posix()
            con.execute(
                f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{glob}', "
                "hive_partitioning=true, union_by_name=true)"
            )
            present.append(table)
    if "gp_elements" in present:
        con.execute(GP_VIEWS_SQL)
    if "satcat" in present:
        con.execute(SATCAT_VIEWS_SQL)
    return con
