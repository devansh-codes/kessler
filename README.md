# Kessler data branch

Orphan branch holding the Parquet warehouse written by the scheduled `ingest` workflow.
Hive-partitioned tables live under `warehouse/<table>/`; `_state.json` tracks per-source cadence.

Raw element sets here come from CelesTrak (Dr. T.S. Kelso; 18 SDS / Space-Track) and are kept
only so CI can recompute derived products. The public site publishes derived products only.
GCAT tables: McDowell, Jonathan C., 2020. General Catalog of Artificial Space Objects (CC-BY 4.0).
