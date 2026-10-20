// SQL Lab: DuckDB-WASM, lazy-loaded on this route only, self-hosted (same origin, no CDN).
import { api, BASE } from "../api";
import { errorBox, fmtNum, h, loading } from "../ui";

const MAX_ROWS = 5000;
const TABLES = ["events", "breakup_solutions", "event_fragments", "fragment_dv", "gabbard_points", "reentry_forecasts", "reentry_backtest", "decayed_objects", "scorecard"];

const STARTERS: { label: string; sql: string }[] = [
  {
    label: "Fragments with |Δv| > 20 m/s",
    sql: `SELECT event_id, norad_cat_id, round(dv_mag, 1) AS dv_ms,
       round(dv_r, 1) AS radial, round(dv_t, 1) AS transverse, round(dv_n, 1) AS normal,
       round(residual_km, 1) AS orbit_miss_km
FROM fragment_dv
WHERE dv_mag > 20 AND reliable
ORDER BY dv_mag DESC;`,
  },
  {
    label: "Breakup solutions",
    sql: `SELECT e.event_id, e.title, e.mode, e.n_fragments,
       s.t_p50 AS breakup_utc, round(e.reference_delta_min / 60, 2) AS hours_vs_reported,
       round(s.lat, 2) AS lat, round(s.lon, 2) AS lon, round(s.alt_km) AS alt_km, s.flags
FROM events e LEFT JOIN breakup_solutions s USING (event_id)
ORDER BY e.n_fragments DESC;`,
  },
  {
    label: "Soonest predicted reentries",
    sql: `SELECT object_name, norad_cat_id, object_type, round(perigee_km) AS perigee_km,
       p10::DATE AS early, p50::DATE AS median, p90::DATE AS late, model_version
FROM reentry_forecasts
QUALIFY row_number() OVER (PARTITION BY norad_cat_id ORDER BY issued_at DESC) = 1
ORDER BY p50
LIMIT 25;`,
  },
  {
    label: "Debris per launch by rocket family",
    sql: `SELECT family, launches, stage_debris, round(debris_per_launch, 2) AS per_launch, frag_events
FROM scorecard
WHERE launches >= 10
ORDER BY per_launch DESC
LIMIT 15;`,
  },
  {
    label: "Reentries per month (training set)",
    sql: `SELECT date_trunc('month', decay_date::DATE) AS month, object_type, count(*) AS objects
FROM decayed_objects
GROUP BY ALL
ORDER BY month DESC, objects DESC
LIMIT 48;`,
  },
  {
    label: "Gabbard spread per snapshot",
    sql: `SELECT event_id, snapshot::DATE AS snapshot, count(*) AS objects,
       round(min(peri)) AS lowest_perigee_km, round(max(apo)) AS highest_apogee_km,
       round(max(period) - min(period), 2) AS period_spread_min
FROM gabbard_points
GROUP BY ALL
ORDER BY event_id, snapshot;`,
  },
];

type Conn = { query: (sql: string) => Promise<{ numRows: number; schema: { fields: { name: string }[] }; toArray(): { toJSON(): Record<string, unknown> }[] }> };

let dbPromise: Promise<Conn> | null = null;

async function getDb(onStatus: (s: string) => void): Promise<Conn> {
  if (dbPromise) return dbPromise;
  dbPromise = (async () => {
    onStatus("Downloading DuckDB-WASM…");
    const duckdb = await import("@duckdb/duckdb-wasm");
    const wasmUrl = (await import("@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url")).default;
    const workerUrl = (await import("@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url")).default;
    const worker = new Worker(workerUrl);
    const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
    await db.instantiate(wasmUrl);
    const conn = await db.connect();
    onStatus("Registering tables…");
    const manifest = await api.manifest().catch(() => null);
    const available = new Set(Object.keys(manifest?.files ?? {}));
    for (const t of TABLES) {
      const path = `sql/${t}.parquet`;
      if (manifest && !available.has(path)) continue;
      const url = new URL(`${BASE}data/${path}`, location.href).toString();
      await db.registerFileURL(`${t}.parquet`, url, duckdb.DuckDBDataProtocol.HTTP, false);
      await conn.query(`CREATE OR REPLACE VIEW ${t} AS SELECT * FROM read_parquet('${t}.parquet')`);
    }
    return conn as unknown as Conn;
  })();
  dbPromise.catch(() => (dbPromise = null));
  return dbPromise;
}

export async function render(root: HTMLElement): Promise<() => void> {
  const status = h("span", { class: "small muted", role: "status" }, "");
  const editor = h("textarea", { class: "sql-editor", spellcheck: "false", "aria-label": "SQL query" }) as HTMLTextAreaElement;
  editor.value = STARTERS[0].sql;
  const run = h("button", { class: "btn primary", type: "button" }, "Run ⌘↵");
  const results = h("div", {});
  const schema = h("div", { class: "small secondary" });
  const chips = h("div", { class: "chips" }, ...STARTERS.map((s) => {
    const b = h("button", { class: "chip", type: "button" }, s.label);
    b.addEventListener("click", () => { editor.value = s.sql; exec(); });
    return b;
  }));

  root.append(
    h(
      "div",
      { class: "wrap" },
      h(
        "header",
        { class: "event-head stack" },
        h("p", { class: "eyebrow" }, "SQL Lab"),
        h("h1", {}, "Query the derived data in your browser"),
        h("p", { class: "lede" }, "DuckDB compiled to WebAssembly runs entirely in this tab, over the same Parquet tables the pipeline produced. Nothing is sent to a server."),
      ),
      h(
        "section",
        { class: "panel stack", style: "margin-top:20px" },
        h("p", { class: "small secondary" }, "Starter queries"),
        chips,
        editor,
        h("div", { class: "row" }, run, status, h("span", { class: "spacer" }), h("span", { class: "small muted" }, `Results capped at ${MAX_ROWS.toLocaleString()} rows.`)),
      ),
      h("section", { class: "panel", style: "margin-top:16px" }, h("div", { class: "panel-head" }, h("h2", {}, "Results")), results),
      h("section", { class: "panel", style: "margin:16px 0 48px" }, h("div", { class: "panel-head" }, h("h2", {}, "Tables")), schema),
    ),
  );

  async function exec(): Promise<void> {
    results.replaceChildren(loading("Running…"));
    run.setAttribute("disabled", "");
    try {
      const conn = await getDb((s) => (status.textContent = s));
      status.textContent = "Running…";
      const t0 = performance.now();
      const sql = editor.value.trim().replace(/;\s*$/, "");
      const res = await conn.query(`SELECT * FROM (${sql}) LIMIT ${MAX_ROWS + 1}`);
      const ms = performance.now() - t0;
      const rows = res.toArray().map((r) => r.toJSON());
      const cols = res.schema.fields.map((f) => f.name);
      const capped = rows.length > MAX_ROWS;
      status.textContent = `${fmtNum(Math.min(rows.length, MAX_ROWS))} row(s) in ${fmtNum(ms, 0)} ms${capped ? " · capped" : ""}`;
      results.replaceChildren(table(cols, rows.slice(0, MAX_ROWS)));
    } catch (e) {
      status.textContent = "";
      results.replaceChildren(errorBox(e));
    } finally {
      run.removeAttribute("disabled");
    }
  }
  run.addEventListener("click", exec);
  editor.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); exec(); }
  });

  // describe tables once the engine is up
  exec().then(async () => {
    const conn = await getDb(() => undefined);
    const parts: HTMLElement[] = [];
    for (const t of TABLES) {
      try {
        const r = await conn.query(`DESCRIBE ${t}`);
        const n = await conn.query(`SELECT count(*) AS n FROM ${t}`);
        const cnt = Number(n.toArray()[0].toJSON().n);
        const cols = r.toArray().map((x) => x.toJSON()).map((c) => `${c.column_name} ${String(c.column_type).toLowerCase()}`);
        parts.push(h("p", { style: "margin-top:8px" }, h("code", {}, t), ` ${fmtNum(cnt)} rows · `, h("span", { class: "muted mono", style: "font-size:12px" }, cols.join(", "))));
      } catch { /* table not published yet */ }
    }
    schema.replaceChildren(...parts);
  }).catch(() => undefined);
  return () => undefined;
}

function cell(v: unknown): string {
  if (v === null || v === undefined) return "NULL";
  if (typeof v === "bigint") return v.toString();
  if (v instanceof Date) return v.toISOString();
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/\.?0+$/, "");
  if (typeof v === "object") return JSON.stringify(v, (_, x) => (typeof x === "bigint" ? x.toString() : x));
  return String(v);
}

function table(cols: string[], rows: Record<string, unknown>[]): HTMLElement {
  if (!rows.length) return h("p", { class: "muted" }, "No rows.");
  const isNum = cols.map((c) => rows.every((r) => r[c] === null || typeof r[c] === "number" || typeof r[c] === "bigint"));
  const fmtTs = (c: string, v: unknown) => (typeof v === "number" && /epoch|_at|^t_|date|snapshot|p10|p50|p90|baseline|breakup/.test(c) && v > 1e11 ? new Date(v).toISOString().replace(".000Z", "Z") : cell(v));
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      {},
      h("thead", {}, h("tr", {}, ...cols.map((c, i) => h("th", { class: isNum[i] ? "n" : "" }, c)))),
      h("tbody", {}, ...rows.map((r) => h("tr", {}, ...cols.map((c, i) => h("td", { class: isNum[i] ? "n" : "" }, fmtTs(c, r[c])))))),
    ),
  );
}
