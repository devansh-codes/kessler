# KESSLER — Orbital Breakup Forensics Lab

### Build specification (backend, database, frontend, CI/CD, deployment)

> Research for this plan was done on **2026-10-19**. Items originally marked **[VERIFY]** were checked on 2026-10-19; results are in **Appendix A**.

---

## 0. One-paragraph pitch

Kessler reconstructs 2026's satellite and rocket-stage breakups using only public orbital data. For each event it estimates **when and where the object fragmented**, computes each fragment's **velocity kick (Δv)**, animates the **debris cloud on a 3D globe**, tracks the cloud's **decay and reentry** under real space weather, and ranks **launch vehicles and stages by the debris they leave behind**. Everything runs serverless: Python pipelines on GitHub Actions write a Parquet/DuckDB warehouse, export static data products, and a Vite/TypeScript site on GitHub Pages renders them, including an in-browser SQL lab (DuckDB-WASM).

---

## 1. Why these events

| Event ID | Object | When (reference) | Reference source | Notes |
|---|---|---|---|---|
| `starlink-34343` | STARLINK-34343 | 2026-03-29 | SpaceX/Starlink statement; LeoLabs | ~560 km. SpaceX attributed it to an internal energetic source. Fragments expected to deorbit within weeks, so use CelesTrak first-GP queries to recover them after decay. |
| `starlink-35956` | STARLINK-35956 | 2025-12-17 | LeoLabs | Earlier sibling event; second test case. |
| `cz6c-2026-195` | Long March 6C upper stage, NORAD 100472, 2026-195H | late Aug 2026 (LeoLabs: 02:30, the 27th) | LeoLabs via SpaceNews/FODNews | Rocket-body event; six-digit NORAD IDs. Broke up two days after a 7-satellite rideshare. |
| `usa-32` | USA 32, NORAD 19460, 1988-078A | 2026-09-13 ~21:13 UTC | US Space Forces-Space notice | ~775 km. As of 2026-09-24 no debris catalogued publicly, so this is the parent-only mode test. A third-party element-set analysis put the impulse at 2026-09-14 05:44Z with Δv ≈ 0.30 m/s. |
| `meteor-2-7` | METEOR 2-7, NORAD 12456, 1981-043A | 2026-10-05 09:45 UTC ± 10 min | Jim Shell, LeoLabs | ~855 km. Also broke up in March 2004, so 2004 debris must be separated from 2026 debris (§7.4). |
| `luch-olymp` (stretch) | LUCH (OLYMP), NORAD 40258 | 2026-01-30 06:09 UTC | s2a systems optical imagery | GEO graveyard: deep-space SDP4 path. Stretch goal. |

Context: the catalog crossed NORAD 100000 on 2026-07-11; new objects cannot be represented in TLE format, so this project uses OMM (CSV/JSON) only.

---

## 2. Global rules

1. Never use TLE/3LE/2LE formats. Request `FORMAT=CSV` (or JSON). NORAD IDs are BIGINT everywhere. Unit test with a 6-digit ID (100472).
2. CelesTrak etiquette is mandatory: only `https://celestrak.org`; descriptive User-Agent with contact URL; stop on any non-200, never retry 403/404 (firewall after ~50 errors / 2 h); `No GP data found` = empty, not error; cache every response, never re-request the same query within 2 h; `SW-All.csv` once, then `SW-Last5Years.csv` at most daily.
3. Do not commit or publish Space-Track data.
4. Publish derived products, not raw element sets (`PUBLISH_RAW_OMM=false`).
5. Attribution: CelesTrak (Dr. T.S. Kelso; 18 SDS / Space-Track), GCAT CC-BY 4.0 (`McDowell, Jonathan C., 2020. General Catalog of Artificial Space Objects, Release <x.y.z>, https://planet4589.org/space/gcat`), CelesTrak SpaceData + NOAA SWPC, NASA Visible Earth.
6. Every phase ends with a deploy.
7. Tests or it didn't happen (pytest with recorded fixtures; vitest).
8. No secrets / API keys.
9. Small, typed, documented, idempotent modules.

---

## 3. Architecture

```
 CelesTrak GP / SATCAT / SW, GCAT, NOAA SWPC
        │
        ▼  ingest.yml (cron every 6h): kessler ingest → Parquet on `data` branch
        ▼  publish.yml: kessler build (DuckDB views + compute) → kessler export → site/public/data
        ▼  npm run build → GitHub Pages
 Browser: Vite/TS ── globe.gl ── Observable Plot ── DuckDB-WASM SQL Lab (same-origin Parquet)
```

System of record: partitioned Parquet on an orphan `data` branch. DuckDB is the query engine (in-process in CI, WASM in the browser).

## 4. Tech stack

Python 3.12 (uv): duckdb, pyarrow, pandas, numpy, scipy, sgp4, scikit-learn, ruptures, httpx, pydantic v2, typer, pyyaml, rich; dev: pytest, respx, ruff, mypy.
Frontend: Node 24, Vite + TypeScript, hash router, globe.gl, @observablehq/plot, @duckdb/duckdb-wasm (lazy, SQL page only). satellite.js not used in v1.
CI/CD: GitHub Actions (versions in Appendix A), astral-sh/setup-uv.

## 5. Repository layout

See the repository tree; module map: `src/kessler/{cli,http}.py`, `sources/`, `warehouse/`, `orbits/`, `forensics/`, `reentry/`, `scorecard/`, `export/`; `site/`; `.github/workflows/{ci,ingest,publish}.yml`.

## 6. Data sources

- GP: `https://celestrak.org/NORAD/elements/gp.php?{CATNR|INTDES|GROUP|NAME|SPECIAL}=V&FORMAT=CSV`; first GP: `gp-first.php` (same params).
- SATCAT: `https://celestrak.org/satcat/records.php?{QUERY}=V&FORMAT=CSV` (flags PAYLOADS, ONORBIT, ACTIVE, MAX). DECAY_DATE is day precision (±12 h label noise).
- Space weather: `SW-All.csv` once, then `SW-Last5Years.csv` daily; NOAA SWPC Kp + F10.7 JSON for live strip.
- GCAT: `tsv/cat/satcat.tsv`, `tsv/cat/satcat100k.tsv`, `tsv/launch/launch.tsv`; weekly; store release string.
- Event registry: `config/events.yaml`.

## 7. Algorithms

- 7.1 Elements: a = (μ/n²)^(1/3); apo/peri = a(1±e) − R⊕; period = 1440/n. Gabbard diagram.
- 7.2 Breakup epoch: window [ref−3 d, min first fragment epoch], 60 s coarse grid (SatrecArray, TEME), objective median‖r_i − r_parent‖ (plus parent-free sqrt(trace cov)), bounded refine ±10 min, 500-sample bootstrap (p5/p50/p95), second-element-set sensitivity, location via GMST→ECEF→geodetic, flags (LOW_CONFIDENCE if spread > 200 km).
- 7.3 Δv per fragment in RTN at t*; log-normal fit for |dv|; median, p90.
- 7.4 Membership: INTDES candidates + time filter + DBSCAN on plane-normal/inclination/RAAN features; persist assignment_method and cluster_label.
- 7.5 Parent-only: changepoint on parent MEAN_MOTION / ECCENTRICITY / BSTAR; Δv_t ≈ (n·a/2)(Δa/a).
- 7.6 Reentry: last-GP + DECAY_DATE training set (≤50 req/day, batched), physics baseline t ≈ (n_crit − n)/(2·ṅ), quantile HistGBR on log(days) + split-conformal on a time-ordered holdout; MAE, coverage, lead time, skill; live forecasts stored with issued_at and scored later.
- 7.7 Scorecard: GCAT satcat(+100k) ⨝ launch on Launch_Tag; per LV family / stage: R/B in orbit, debris from stages, fragmentation events, median days to first debris.

## 8. Warehouse schema and export contract

Parquet tables: gp_elements, satcat, space_weather, kp_live, gcat_objects, gcat_launches, ingest_log (hive-partitioned, deduped on key, <5 MB parts, `_SCHEMA_VERSION`).
Derived: events, event_fragments, breakup_solutions, fragment_dv, gabbard_points, reentry_forecasts, reentry_backtest, scorecard.
Frontend contract under `site/public/data/`: manifest.json, events/index.json, events/<id>/{summary,gabbard,dv}.json, ephem.bin (Float32 LE [T][N][3] lat,lon,alt) + ephem.meta.json, reentry/*.json, spaceweather.json, scorecard.json, sql/*.parquet. Budgets: ephem.bin ≤ 15 MB, total ≤ 250 MB; export fails if exceeded.

## 9. Frontend

Hash routes `#/`, `#/event/:id`, `#/reentry`, `#/scorecard`, `#/sql`, `#/methods`, `#/status`; Vite base `/kessler/`. Breakup Board, event page (globe, Gabbard, Δv, membership, reentry curve, disagreements), Reentry Watch, Scorecard, SQL Lab (DuckDB-WASM lazy, 6 starter queries, 5,000-row cap), Methods, Status. Initial JS < 250 KB gz excluding code-split globe/DuckDB; LCP < 3 s; data-table toggles, keyboard timeline, prefers-reduced-motion.

## 10. CI/CD

ci.yml (ruff, pytest, typecheck, vitest, build), ingest.yml (cron `23 */6 * * *`, commits to `data`), publish.yml (build → export → Vite build → Pages). Pages limits: ≤1 GB, 100 GB/month, 10-minute deploy timeout.

## 11. Phases

0 Scaffold + hello-orbit deploy · 1 Ingestion & warehouse + Status page · 2 Orbit core + first event view · 3 Breakup forensics + validation · 4 Globe animation & ephemerides · 5 Reentry forecaster · 6 Scorecard & SQL Lab · 7 Hardening & storytelling. Each phase ends deployed.

## 12–14. Testing, risks, definition of done

Recorded HTTP fixtures only (live smoke test opt-in), golden SGP4 vectors, synthetic fake-breakup regression test, vitest for ephem decoder. Done = live auto-updating site, ≥4 reconstructed events with validation, published reentry backtest, SQL lab, README "what went wrong".

---

## Appendix A — Verification results (2026-10-19)

| Item | Finding |
|---|---|
| CelesTrak first GP | `https://celestrak.org/NORAD/elements/gp-first.php?INTDES=yyyy-nnn&FORMAT=CSV` (also NAME, CATNR). |
| CelesTrak last GP | No documented standalone endpoint. CelesTrak exposes last-GP data via the table `https://celestrak.org/satcat/decayed-with-last.php`; Kessler falls back to accumulating its own snapshots plus `gp-first.php` + SATCAT DECAY_DATE. |
| CSV default | Confirmed: CSV default since 2026-05-09; TLE cannot represent > 99999. |
| Etiquette | Confirmed: GP checked every 2 h; 50 errors / 2 h → firewall; repeat requests before update return 403. |
| SW CSV columns | DATE, BSRN, ND, KP1–KP8, KP_SUM, AP1–AP8, AP_AVG, CP, C9, ISN, F10.7_OBS, F10.7_ADJ, F10.7_DATA_TYPE, F10.7_OBS_CENTER81, F10.7_OBS_LAST81, F10.7_ADJ_CENTER81, F10.7_ADJ_LAST81. |
| GCAT object columns | JCAT, Satcat, Launch_Tag, Piece, Type (P/R/C/D prefix), Name, PLName, LDate, Parent, SDate, Primary, DDate, Status, Dest, Owner, State, …, Perigee, PF, Apogee, AF, Inc, IF, OpOrbit, OQUAL, AltNames. Debris origin is encoded in Name ("X deb"). |
| Actions versions | checkout v7, setup-node v7, configure-pages v6, upload-pages-artifact v5, deploy-pages v5, cache v6, astral-sh/setup-uv v10.3.0 (no floating major tag is published for setup-uv v10; pin the exact version). |
| npm | vite 8.3, @duckdb/duckdb-wasm 1.33.1-dev57 (latest tag), globe.gl 2.46, three 0.186, @observablehq/plot 0.6.17, vitest 5. |
