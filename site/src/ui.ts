// Tiny DOM helpers: no framework, typed and small.

type Attrs = Record<string, string | number | boolean | null | undefined | ((e: Event) => void)>;
type Child = Node | string | number | null | undefined | false | Child[];

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Attrs = {}, ...children: Child[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (typeof v === "function") el.addEventListener(k.replace(/^on/, "").toLowerCase(), v as EventListener);
    else if (k === "class") el.className = String(v);
    else if (k === "html") el.innerHTML = String(v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  append(el, children);
  return el;
}

function append(el: Node, children: Child[]): void {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function svgEl(tag: string, attrs: Record<string, string | number> = {}): SVGElement {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

const UTC_FMT = new Intl.DateTimeFormat("en-GB", {
  year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "UTC", hour12: false,
});
const DATE_FMT = new Intl.DateTimeFormat("en-GB", { year: "numeric", month: "short", day: "2-digit", timeZone: "UTC" });

export function fmtUTC(iso: string | null | undefined): string {
  if (!iso) return "—";
  return UTC_FMT.format(new Date(iso)).replace(",", "") + "Z";
}
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return DATE_FMT.format(new Date(iso));
}
export function fmtNum(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}
export function fmtCompact(v: number): string {
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}
export function fmtMinutes(min: number | null | undefined): string {
  if (min === null || min === undefined) return "—";
  const a = Math.abs(min);
  const sign = min < 0 ? "−" : "+";
  if (a < 90) return `${sign}${a.toFixed(a < 10 ? 1 : 0)} min`;
  if (a < 60 * 48) return `${sign}${(a / 60).toFixed(1)} h`;
  return `${sign}${(a / 1440).toFixed(1)} d`;
}
export function relTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const s = (now - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export const FLAG_TEXT: Record<string, { label: string; level: "good" | "warning" | "serious" | "critical" | "info"; help: string }> = {
  LOW_CONFIDENCE: { label: "Low confidence", level: "serious", help: "The cloud never converges tightly; treat the time as indicative." },
  FEW_FRAGMENTS: { label: "Few fragments", level: "warning", help: "Fewer than the minimum fragments needed for a robust fit." },
  NO_PUBLIC_FRAGMENTS: { label: "No public fragments", level: "warning", help: "No debris from this event has been catalogued publicly yet." },
  PARENT_ONLY: { label: "Parent-only mode", level: "info", help: "Estimated from the parent object's own element history." },
  STALE_PARENT: { label: "Stale parent", level: "warning", help: "Parent elements are far from the solution epoch." },
  LONG_BACKPROP: { label: "Long back-propagation", level: "warning", help: "Fragments were catalogued weeks after the event; SGP4 error grows with time." },
  INSUFFICIENT_HISTORY: { label: "Insufficient history", level: "warning", help: "Not enough element sets bracket the event yet. Accuracy improves as snapshots accumulate." },
  STRETCH: { label: "Stretch case", level: "info", help: "Deep-space event; experimental." },
  MULTIMODAL: { label: "Several revolutions fit", level: "warning", help: "Bootstrap resamples pick different orbital revolutions; the interval spans more than one orbit." },
  PROPAGATION_FAILED: { label: "Propagation failed", level: "critical", help: "SGP4 could not propagate the element sets over the search window." },
  OUTLIERS: { label: "Outliers removed", level: "info", help: "Fragments whose closest approach exceeded 3× the median were excluded." },
};

export function flagBadge(flag: string): HTMLElement {
  const f = FLAG_TEXT[flag] ?? { label: flag, level: "info", help: flag };
  return h("span", { class: `badge ${f.level}`, title: f.help }, h("span", { class: "dot", "aria-hidden": "true" }), f.label);
}

export function loading(msg = "Loading…"): HTMLElement {
  return h("div", { class: "loading", role: "status" }, msg);
}

export function errorBox(err: unknown, hint = ""): HTMLElement {
  const msg = err instanceof Error ? err.message : String(err);
  return h("div", { class: "error-box", role: "alert" }, h("strong", {}, "Couldn't load this view. "), msg, hint ? h("p", { class: "small muted" }, hint) : null);
}

export function prefersReducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

/** A panel with a title, optional subtitle, chart body and a chart↔table toggle. */
export function chartPanel(opts: {
  title: string;
  subtitle?: string;
  chart: HTMLElement;
  table?: () => HTMLElement;
  legend?: HTMLElement | null;
  extra?: HTMLElement | null;
}): HTMLElement {
  const body = h("div", { class: "chart" }, opts.chart);
  let showingTable = false;
  const btn = opts.table
    ? h("button", { class: "btn toggle-table", type: "button", "aria-pressed": "false" }, "Table")
    : null;
  if (btn && opts.table) {
    const makeTable = opts.table;
    btn.addEventListener("click", () => {
      showingTable = !showingTable;
      btn.setAttribute("aria-pressed", String(showingTable));
      btn.textContent = showingTable ? "Chart" : "Table";
      body.replaceChildren(showingTable ? makeTable() : opts.chart);
    });
  }
  return h(
    "section",
    { class: "panel" },
    h("div", { class: "panel-head" }, h("div", {}, h("h2", {}, opts.title), opts.subtitle ? h("p", {}, opts.subtitle) : null), h("div", { class: "row" }, opts.extra ?? null, btn)),
    opts.legend ?? null,
    body,
  );
}

export function dataTable<T extends Record<string, unknown>>(
  rows: T[],
  cols: { key: keyof T & string; label: string; num?: boolean; fmt?: (v: unknown, row: T) => string | Node }[],
  opts: { maxRows?: number; sortable?: boolean; initialSort?: { key: keyof T & string; dir: 1 | -1 } } = {},
): HTMLElement {
  const max = opts.maxRows ?? 2000;
  let sortKey = opts.initialSort?.key ?? null;
  let dir: 1 | -1 = opts.initialSort?.dir ?? 1;
  const tbody = h("tbody");
  const render = () => {
    let data = rows;
    if (sortKey) {
      const k = sortKey;
      data = [...rows].sort((a, b) => {
        const av = a[k] as unknown, bv = b[k] as unknown;
        if (av === bv) return 0;
        if (av === null || av === undefined) return 1;
        if (bv === null || bv === undefined) return -1;
        return (av < bv ? -1 : 1) * dir;
      });
    }
    tbody.replaceChildren(
      ...data.slice(0, max).map((r) =>
        h("tr", {}, ...cols.map((c) => {
          const v = r[c.key];
          const content = c.fmt ? c.fmt(v, r) : v === null || v === undefined ? "—" : typeof v === "number" ? fmtNum(v, Number.isInteger(v) ? 0 : 2) : String(v);
          return h("td", { class: c.num ? "n" : "" }, content);
        })),
      ),
    );
  };
  const ths = cols.map((c) => {
    const th = h("th", { class: c.num ? "n" : "", scope: "col", "data-sort": opts.sortable ? c.key : null, tabindex: opts.sortable ? 0 : null }, c.label);
    if (opts.sortable) {
      const go = () => {
        dir = sortKey === c.key ? ((-dir) as 1 | -1) : 1;
        sortKey = c.key;
        ths.forEach((t) => t.removeAttribute("aria-sort"));
        th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
        render();
      };
      th.addEventListener("click", go);
      th.addEventListener("keydown", (e) => { if ((e as KeyboardEvent).key === "Enter") go(); });
    }
    return th;
  });
  render();
  const wrap = h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ...ths)), tbody));
  if (rows.length > max) wrap.appendChild(h("p", { class: "small muted", style: "padding:8px 12px" }, `Showing ${max.toLocaleString()} of ${rows.length.toLocaleString()} rows.`));
  return wrap;
}
