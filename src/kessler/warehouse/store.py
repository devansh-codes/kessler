"""Append + deduplicate writes into hive-partitioned Parquet.

Each touched partition is rewritten as a single ``part-0.parquet`` (split into more parts if it
would exceed ``MAX_PART_BYTES``). Writes are idempotent: writing the same frame twice leaves the
warehouse byte-for-byte equivalent in content.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from kessler.warehouse.schema import SCHEMA_VERSION, TABLES, TableSpec

MAX_PART_ROWS = 200_000  # keeps parts well under 5 MB for our column sets


def _partition_dirs(spec: TableSpec, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if spec.partition_col is None:
        return {"": df}
    ts = pd.to_datetime(df[spec.partition_col], utc=True)
    if spec.granularity == "year":
        keys = ts.dt.strftime("year=%Y")
    else:
        keys = ts.dt.strftime("year=%Y/month=%m")
    return {k: g for k, g in df.groupby(keys.values, sort=True)}


def _read_dir(d: Path) -> pd.DataFrame | None:
    files = sorted(d.glob("part-*.parquet"))
    if not files:
        return None
    return pd.concat([pq.read_table(f).to_pandas() for f in files], ignore_index=True)


def _dedupe(spec: TableSpec, df: pd.DataFrame) -> pd.DataFrame:
    key = list(spec.key)
    flags = [f for f in spec.or_flags if f in df.columns]
    if flags:
        agg = df.groupby(key, dropna=False)[flags].transform("max")
        df = df.assign(**{f: agg[f].astype(bool) for f in flags})
    # keep the first-seen row for each key (stable history), flags already merged
    sort_cols = [c for c in ("fetched_at",) if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, kind="stable")
    df = df.drop_duplicates(subset=key, keep=spec.keep)
    return df.sort_values(key, kind="stable").reset_index(drop=True)


def _write_dir(d: Path, df: pd.DataFrame) -> None:
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("part-*.parquet"):
        old.unlink()
    for i, start in enumerate(range(0, max(len(df), 1), MAX_PART_ROWS)):
        chunk = df.iloc[start : start + MAX_PART_ROWS]
        table = pa.Table.from_pandas(chunk, preserve_index=False)
        pq.write_table(table, d / f"part-{i}.parquet", compression="zstd")


def write(warehouse: Path, table: str, df: pd.DataFrame) -> int:
    """Merge ``df`` into ``table``. Returns the number of genuinely new key rows."""
    spec = TABLES[table]
    warehouse = Path(warehouse)
    _ensure_version(warehouse)
    if df is None or df.empty:
        return 0
    root = warehouse / table
    if spec.replace:
        before = _read_dir(root)
        new = _dedupe(spec, df)
        n_before = 0 if before is None else len(before)
        _write_dir(root, new)
        return max(len(new) - n_before, 0) if before is not None else len(new)

    added = 0
    for part, chunk in _partition_dirs(spec, df).items():
        d = root / part if part else root
        existing = _read_dir(d)
        n_before = 0 if existing is None else len(existing)
        merged = chunk if existing is None else pd.concat([existing, chunk], ignore_index=True)
        merged = _dedupe(spec, _align(merged))
        added += len(merged) - n_before
        _write_dir(d, merged)
    return added


def read(warehouse: Path, table: str) -> pd.DataFrame:
    root = Path(warehouse) / table
    files = sorted(root.rglob("part-*.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pq.read_table(f).to_pandas() for f in files], ignore_index=True)


def _align(df: pd.DataFrame) -> pd.DataFrame:
    # concat of frames with differing dtypes (e.g. all-null object vs float) -> keep pandas inference
    return df.infer_objects()


def _ensure_version(warehouse: Path) -> None:
    warehouse.mkdir(parents=True, exist_ok=True)
    f = warehouse / "_SCHEMA_VERSION"
    if not f.exists():
        f.write_text(f"{SCHEMA_VERSION}\n")
