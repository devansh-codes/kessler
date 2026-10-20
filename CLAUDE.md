# Kessler: rules for working in this repo

Spec: `KESSLER_PLAN.md`. These rules apply to every change.

1. **No TLE/3LE/2LE, ever.** Request `FORMAT=CSV` (or JSON). NORAD IDs are BIGINT/int64 everywhere; six-digit IDs (e.g. 100472) must round-trip.
2. **CelesTrak etiquette** (they firewall abusive IPs, including GitHub runners):
   - `https://celestrak.org` only (never `.com`); descriptive User-Agent with contact URL (`kessler.http.USER_AGENT`).
   - Stop on any non-200. Never retry 403/404. `PoliteClient` enforces this and keeps an error ledger.
   - `No GP data found` = empty result, not an error.
   - Cache every response; never re-request the same URL within 2 h. GP data updates every ~2 h.
   - `SW-All.csv` once; afterwards `SW-Last5Years.csv` at most daily.
   - Reentry backfill: at most 40 requests/day (see `config/settings.yaml`).
   - Never add network calls outside `kessler.http.PoliteClient`. Never parallelise requests.
3. **No Space-Track data** in git or on the site.
4. **Publish derived products only** (`PUBLISH_RAW_OMM=false`); raw OMM stays on the `data` branch.
5. **Attribution** (Methods page + README): CelesTrak (Dr. T.S. Kelso; 18 SDS/Space-Track); GCAT CC-BY 4.0 citation with release; CelesTrak SpaceData + NOAA SWPC; NASA Visible Earth.
6. **Every phase ends with a deploy**; keep Pages green.
7. **Tests or it didn't happen**: pytest with recorded fixtures in `tests/fixtures/` (no live network; `@pytest.mark.live` is opt-in); vitest for the site.
8. No secrets or API keys are needed or allowed.
9. Small, typed, idempotent modules. Every pipeline step is re-runnable.

## Commands
- `uv run kessler ingest -w warehouse_repo/warehouse` · `build` · `export --out site/public/data` · `status`
- `uv run pytest -q` · `uv run ruff check .`
- `cd site && npm run dev | typecheck | test | build`
- Data lives on the orphan `data` branch (`git worktree add warehouse_repo data`).
