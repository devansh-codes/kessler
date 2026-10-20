import { api } from "../api";
import { dataTable, errorBox, fmtNum, fmtUTC, h, loading, relTime } from "../ui";

const EXPECTED_H: Record<string, number> = { celestrak_gp: 8, celestrak_satcat: 30, celestrak_sw: 30, noaa_swpc: 8, gcat: 24 * 8 };

export async function render(root: HTMLElement): Promise<void> {
  const wrap = h("div", { class: "wrap" });
  root.append(wrap);
  wrap.append(loading("Loading status…"));
  let m;
  try {
    m = await api.manifest();
  } catch (e) {
    wrap.replaceChildren(h("div", { class: "section" }, errorBox(e)));
    return;
  }
  const st = m.ingest_status;
  const last = st.last_run;
  const ageH = last ? (Date.now() - new Date(last.started_at).getTime()) / 3600e3 : Infinity;
  const health = !last ? ["critical", "No ingest has run yet"] : ageH > 13 ? ["serious", `Last ingest ${relTime(last.started_at)}: the schedule may have stalled`] : last.status !== "ok" ? ["warning", `Last ingest finished as "${last.status}"`] : ["good", "All sources ingesting normally"];
  const errors = st.http.filter((r) => r.status !== 200 && !r.from_cache);
  wrap.replaceChildren(
    h(
      "header",
      { class: "event-head stack" },
      h("p", { class: "eyebrow" }, "Operations"),
      h("h1", {}, "Pipeline status"),
      h("p", { class: "lede" }, "Kessler ingests on a 6-hour schedule, politely: responses are cached for 2 hours and the run stops at the first CelesTrak error. This page shows what happened."),
      h("div", { class: "row" }, h("span", { class: `badge ${health[0]}` }, h("span", { class: "dot" }), health[1])),
    ),
    h(
      "section",
      { class: "grid grid-4", style: "margin-top:24px" },
      tile("Last ingest", last ? relTime(last.started_at) : "never", last ? `${fmtUTC(last.started_at)} · ${last.status}` : ""),
      tile("Network calls (last run)", last ? fmtNum(last.network_calls) : "—", "cache hits are free"),
      tile("HTTP errors in log", fmtNum(errors.length), errors.length ? "see the request log below" : "no non-200 responses"),
      tile("Site data generated", relTime(m.generated_at), `${fmtUTC(m.generated_at)} · schema v${m.schema_version}`),
    ),
    h(
      "section",
      { class: "panel", style: "margin-top:16px" },
      h("div", { class: "panel-head" }, h("h2", {}, "Sources"), h("p", {}, "Freshness compared with each source's expected cadence.")),
      dataTable(m.sources as unknown as Record<string, unknown>[], [
        { key: "label", label: "Source", fmt: (v, r) => h("a", { href: String((r as { url: string }).url), rel: "noopener" }, String(v)) },
        { key: "last_success", label: "Last success", fmt: (v) => (v ? `${fmtUTC(v as string)} (${relTime(v as string)})` : "—") },
        {
          key: "id",
          label: "Freshness",
          fmt: (v, r) => {
            const ls = (r as { last_success: string | null }).last_success;
            const exp = EXPECTED_H[v as string];
            if (!exp) return h("span", { class: "badge" }, "static");
            if (!ls) return h("span", { class: "badge critical" }, h("span", { class: "dot" }), "never");
            const age = (Date.now() - new Date(ls).getTime()) / 3600e3;
            return age <= exp ? h("span", { class: "badge good" }, h("span", { class: "dot" }), "fresh") : h("span", { class: "badge warning" }, h("span", { class: "dot" }), "stale");
          },
        },
        { key: "license", label: "Terms / attribution" },
      ]),
    ),
    h(
      "section",
      { class: "grid grid-2", style: "margin-top:16px" },
      h(
        "div",
        { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", {}, "Recent runs")),
        dataTable([...st.runs].reverse() as unknown as Record<string, unknown>[], [
          { key: "started_at", label: "Started", fmt: (v) => fmtUTC(v as string) },
          { key: "status", label: "Status", fmt: (v) => h("span", { class: `badge ${v === "ok" ? "good" : "warning"}` }, h("span", { class: "dot" }), String(v)) },
          { key: "network_calls", label: "Requests", num: true },
          { key: "rows_new", label: "New rows", num: true, fmt: (v) => fmtNum(Object.values((v ?? {}) as Record<string, number>).reduce((a, b) => a + b, 0)) },
        ]),
      ),
      h(
        "div",
        { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", {}, "Warehouse"), h("p", {}, st.backfill_remaining != null ? `${fmtNum(st.backfill_remaining)} decayed launches still queued for reentry backfill` : "")),
        dataTable(Object.entries(st.table_rows).map(([table, rows]) => ({ table, rows })), [
          { key: "table", label: "Table", fmt: (v) => h("code", {}, String(v)) },
          { key: "rows", label: "Rows", num: true },
        ]),
      ),
    ),
    h(
      "section",
      { class: "panel", style: "margin-top:16px" },
      h("div", { class: "panel-head" }, h("h2", {}, "Last run, task by task")),
      dataTable(st.tasks as unknown as Record<string, unknown>[], [
        { key: "task", label: "Task", fmt: (v) => h("code", {}, String(v)) },
        { key: "status", label: "Outcome" },
        { key: "error", label: "Error", fmt: (v) => (v ? String(v) : "—") },
      ]),
    ),
    h(
      "section",
      { class: "panel", style: "margin:16px 0 48px" },
      h("div", { class: "panel-head" }, h("h2", {}, "HTTP request log"), h("p", {}, "The latest 200 requests. Cache hits make no network call.")),
      dataTable([...st.http].reverse() as unknown as Record<string, unknown>[], [
        { key: "started_at", label: "Time", fmt: (v) => fmtUTC(v as string) },
        { key: "host", label: "Host" },
        { key: "url", label: "URL", fmt: (v) => h("span", { class: "mono", style: "font-size:12px" }, String(v).replace(/^https:\/\//, "")) },
        { key: "status", label: "HTTP", num: true, fmt: (v) => (v === null ? "—" : String(v)) },
        { key: "from_cache", label: "Cache", fmt: (v) => (v ? "hit" : "network") },
        { key: "bytes", label: "Bytes", num: true },
        { key: "duration_ms", label: "ms", num: true },
      ], { maxRows: 200 }),
    ),
  );
}

function tile(l: string, v: string, s: string): HTMLElement {
  return h("div", { class: "tile" }, h("div", { class: "label" }, l), h("div", { class: "value" }, v), h("div", { class: "sub" }, s));
}
