import { api, DataMissing } from "../api";
import type { DvRow, EventSummary, GabbardRow, Reference } from "../types";
import { chartPanel, dataTable, errorBox, flagBadge, fmtDate, fmtMinutes, fmtNum, fmtUTC, h, loading, prefersReducedMotion } from "../ui";
import { C, legendItems, Plot, responsive } from "../viz/plot";

const MODE_TEXT: Record<string, string> = {
  fragments: "Solved from catalogued fragments",
  parent_only: "Parent-only mode: no usable public fragments",
  insufficient: "Insufficient public data",
};

export async function render(root: HTMLElement, params: Record<string, string>): Promise<() => void> {
  const id = params.id;
  const wrap = h("div", { class: "wrap" });
  root.append(wrap);
  wrap.append(loading("Loading event…"));
  const cleanups: (() => void)[] = [];
  let ev: EventSummary;
  try {
    ev = await api.event(id);
  } catch (e) {
    wrap.replaceChildren(h("div", { class: "section" }, errorBox(e, e instanceof DataMissing ? "This event has not been computed yet." : "")));
    return () => undefined;
  }
  const [gab, dv] = await Promise.all([api.gabbard(id).catch(() => [] as GabbardRow[]), api.dv(id).catch(() => [] as DvRow[])]);
  wrap.replaceChildren();

  const sol = ev.solution;
  // ---------------------------------------------------------------- header
  wrap.append(
    h(
      "header",
      { class: "event-head stack" },
      h("a", { href: "#/", class: "small muted" }, "← All breakups"),
      h("p", { class: "eyebrow" }, `${ev.regime} · ${ev.parent.name} · NORAD ${ev.parent.norad} · ${ev.parent.intdes || "—"}`),
      h("h1", {}, ev.title),
      h("p", { class: "lede" }, ev.blurb),
      h("div", { class: "row" }, h("span", { class: "badge info" }, h("span", { class: "dot" }), MODE_TEXT[ev.mode] ?? ev.mode), ...ev.flags.map(flagBadge)),
    ),
  );

  // ---------------------------------------------------------------- tiles
  const ref = ev.references.find((r) => r.kind === "registry");
  const delta = sol?.t_p50 && ref ? (new Date(sol.t_p50).getTime() - new Date(ref.time).getTime()) / 60000 : null;
  const within = delta !== null ? Math.abs(delta) <= ev.reference_precision_hours * 60 : null;
  wrap.append(
    h(
      "section",
      { class: "grid grid-4", style: "margin-top:24px" },
      tile("Breakup time (t*)", sol?.t_p50 ? fmtUTC(sol.t_p50) : "Not solvable yet", sol?.t_p05 && sol?.t_p95 ? `90% CI ${fmtUTC(sol.t_p05)} → ${fmtUTC(sol.t_p95)}` : ev.mode === "fragments" ? "" : "No fragment solution"),
      tile("Versus reported time", delta !== null ? fmtMinutes(delta) : "—", ref ? `${ref.label}${within === null ? "" : within ? " · inside reported precision" : " · outside reported precision"}` : "No reference"),
      tile("Where", sol?.lat != null ? `${fmtNum(Math.abs(sol.lat), 1)}°${sol.lat >= 0 ? "N" : "S"} ${fmtNum(Math.abs(sol.lon!), 1)}°${sol.lon! >= 0 ? "E" : "W"}` : "—", sol?.alt_km != null ? `${fmtNum(sol.alt_km)} km altitude · arg. of latitude ${fmtNum(sol.arg_lat_deg, 0)}°` : ""),
      tile("Fragments", fmtNum(ev.fragments.length), `${ev.fragments.filter((f) => f.decay_date).length} reentered${ev.dv_stats ? ` · Δv median ${fmtNum(ev.dv_stats.median_ms, 0)} m/s, p90 ${fmtNum(ev.dv_stats.p90_ms, 0)} m/s` : ""}`),
    ),
  );

  // ---------------------------------------------------------------- globe
  const shell = h("div", { class: "globe-shell", tabindex: "0", "aria-label": "3D globe of the debris cloud. Press space to play or pause." });
  const globeNote = h("p", { class: "small muted", style: "margin-top:10px" });
  wrap.append(h("section", { class: "section", style: "padding-bottom:16px" }, shell, globeNote));
  if (ev.ephem.available) {
    shell.append(loading("Loading 3D view…"));
    Promise.all([api.ephemMeta(id), import("../viz/debrisplayer")])
      .then(async ([meta, mod]) => {
        shell.replaceChildren();
        cleanups.push(await mod.mountDebrisPlayer(shell, id, meta, Number(params.stress) || 0));
        globeNote.textContent =
          (meta.reconstructed
            ? `First ${(meta.dense_until_s / 3600).toFixed(0)} hours: the cloud is reconstructed. Every fragment starts at the solved breakup point with its fitted Δv and is propagated with two-body + J2 dynamics. After that: SGP4 daily snapshots from catalogued element sets. `
            : meta.t0_kind === "reference" ? "No fragment solution: the timeline starts at the reported event time and shows the parent's orbit (SGP4). " : "")
          + "Fragments fade out at their SATCAT decay date (day precision).";
      })
      .catch((e) => shell.replaceChildren(errorBox(e)));
  } else shell.replaceChildren(h("div", { class: "loading" }, "No ephemeris for this event."));

  // ---------------------------------------------------------------- disagreements
  wrap.append(disagreements(ev));

  // ---------------------------------------------------------------- solver curves
  if (sol && sol.curve && sol.curve.length) {
    wrap.append(h("section", { class: "grid grid-2", style: "margin-top:16px" }, solverChart(ev, "cross", cleanups), solverChart(ev, "spread", cleanups)));
  }

  // ---------------------------------------------------------------- parent-only
  if (ev.parent_only && (ev.mode !== "fragments" || ev.parent_only.series.length > 2)) wrap.append(h("div", { style: "margin-top:16px" }, parentOnlyPanel(ev, cleanups)));

  // ---------------------------------------------------------------- gabbard + dv
  const row2 = h("section", { class: "grid grid-2", style: "margin-top:16px" });
  if (gab.length) row2.append(gabbardPanel(gab, cleanups));
  if (dv.length) row2.append(dvPanel(dv, cleanups));
  if (row2.childElementCount) wrap.append(row2);

  // ---------------------------------------------------------------- membership + decay
  const row3 = h("section", { class: "grid grid-2", style: "margin-top:16px" });
  row3.append(membershipPanel(ev, cleanups));
  if (ev.decay_curve.length) row3.append(decayPanel(ev, cleanups));
  wrap.append(row3);

  // ---------------------------------------------------------------- fragments table
  if (ev.fragments.length) {
    wrap.append(
      h(
        "section",
        { class: "panel", style: "margin:16px 0 48px" },
        h("div", { class: "panel-head" }, h("h2", {}, "Fragments"), h("p", {}, "Δv is measured where each fragment's orbit passes closest to the breakup point. Blank means unreliable (orbit misses the point by more than 500 km).")),
        dataTable(ev.fragments as unknown as Record<string, unknown>[], [
          { key: "norad", label: "NORAD", num: true, fmt: (v) => String(v) },
          { key: "name", label: "Name" },
          { key: "assignment", label: "Assigned by" },
          { key: "first_epoch", label: "First catalogued", fmt: (v) => fmtUTC(v as string) },
          { key: "dv_ms", label: "|Δv| m/s", num: true, fmt: (v) => fmtNum(v as number, 1) },
          { key: "perigee_km", label: "Perigee km", num: true, fmt: (v) => fmtNum(v as number) },
          { key: "apogee_km", label: "Apogee km", num: true, fmt: (v) => fmtNum(v as number) },
          { key: "decay_date", label: "Reentered", fmt: (v) => (v ? fmtDate(v as string) : "in orbit") },
          { key: "forecast_p50", label: "Forecast reentry (p50)", fmt: (v) => (v ? fmtDate(v as string) : "—") },
        ], { sortable: true }),
      ),
    );
  } else wrap.append(h("div", { style: "height:48px" }));

  return () => cleanups.forEach((c) => c());
}

function tile(label: string, value: string, sub: string): HTMLElement {
  return h("div", { class: "tile" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), sub ? h("div", { class: "sub" }, sub) : null);
}

// ===================================================================== disagreements
function disagreements(ev: EventSummary): HTMLElement {
  const sol = ev.solution;
  type Row = { source: string; kind: string; time: string; delta: number | null; note: string };
  const rows: Row[] = [];
  const kindLabel: Record<Reference["kind"], string> = { registry: "Reported", alt: "Independent analysis", gcat: "Catalog (GCAT)", ours: "Kessler", "ours-alt": "Kessler (alt. method)" };
  if (sol?.t_p50) rows.push({ source: "Kessler hybrid solver (this site)", kind: "ours", time: sol.t_p50, delta: null, note: `90% CI ${fmtUTC(sol.t_p05)} → ${fmtUTC(sol.t_p95)}` });
  for (const a of ev.alt_solutions) if (a.t_p50) rows.push({ source: `Kessler · ${a.method} (plan §7.2 as written)`, kind: "ours-alt", time: a.t_p50, delta: sol?.t_p50 ? minutes(a.t_p50, sol.t_p50) : null, note: a.spread_km != null ? `median spread ${fmtNum(a.spread_km)} km` : "" });
  for (const r of ev.references) rows.push({ source: r.label, kind: r.kind, time: r.time, delta: sol?.t_p50 ? minutes(r.time, sol.t_p50) : null, note: r.dv_ms ? `reports Δv ≈ ${r.dv_ms} m/s` : "" });
  const crossings = (sol?.sensitivity ?? []).filter((s) => s.label.startsWith("nearest crossing"));

  const host = h("div", { class: "chart" });
  const tl = () => {
    const times = rows.map((r) => new Date(r.time));
    if (sol?.t_p05) times.push(new Date(sol.t_p05));
    if (sol?.t_p95) times.push(new Date(sol.t_p95));
    return times;
  };
  const cleanup = responsive(host, (w) => {
    const times = tl();
    const pad = Math.max(3600e3, (Math.max(...times.map(Number)) - Math.min(...times.map(Number))) * 0.1);
    return Plot.plot({
      ...base2(w, 40 + rows.length * 30),
      marginLeft: Math.min(260, w * 0.42),
      x: { type: "utc", domain: [new Date(Math.min(...times.map(Number)) - pad), new Date(Math.max(...times.map(Number)) + pad)], grid: true, label: null },
      y: { domain: rows.map((r) => r.source), label: null, tickFormat: (s: string) => { const max = Math.max(14, Math.floor(Math.min(260, w * 0.42) / 6.6)); return s.length > max ? s.slice(0, max - 1) + "…" : s; } },
      marks: [
        sol?.t_p05 && sol?.t_p95 ? Plot.ruleY([rows[0].source], { x1: new Date(sol.t_p05), x2: new Date(sol.t_p95), stroke: C.frag, strokeWidth: 6, strokeOpacity: 0.35, strokeLinecap: "round" }) : null,
        sol?.t_p50 ? Plot.ruleX([new Date(sol.t_p50)], { stroke: C.frag, strokeOpacity: 0.5, strokeDasharray: "2,3" }) : null,
        Plot.dot(rows, { x: (d: Row) => new Date(d.time), y: "source", r: 6, fill: (d: Row) => (d.kind === "ours" ? C.frag : d.kind === "ours-alt" ? C.alt : C.ref), stroke: "#12161d", strokeWidth: 2, tip: true, title: (d: Row) => `${d.source}\n${fmtUTC(d.time)}${d.delta !== null ? `\nours − this: ${fmtMinutes(-d.delta)}` : ""}` }),
      ],
    } as Plot.PlotOptions);
  });
  void cleanup;
  const table = () =>
    dataTable(rows as unknown as Record<string, unknown>[], [
      { key: "source", label: "Source" },
      { key: "kind", label: "Type", fmt: (v) => kindLabel[v as Reference["kind"]] ?? String(v) },
      { key: "time", label: "Time (UTC)", fmt: (v) => fmtUTC(v as string) },
      { key: "delta", label: "This − ours", num: true, fmt: (v) => (v === null ? "—" : fmtMinutes(v as number)) },
      { key: "note", label: "Note" },
    ]);
  const panel = chartPanel({
    title: "Disagreements",
    subtitle: "Every independent estimate of the breakup time, next to ours. Disagreement is the point: each source sees different data.",
    chart: host,
    table,
    legend: legendItems([{ label: "Kessler (hybrid) and 90% CI", color: C.frag }, { label: "Kessler, alternative method", color: C.alt }, { label: "Published references", color: C.ref }]),
  });
  if (crossings.length) {
    panel.append(
      h(
        "div",
        { class: "callout", style: "margin-top:14px" },
        h("strong", {}, "Geometry check. "),
        "The orbit-crossing analysis fixes ",
        h("em", {}, "where"),
        " in the orbit the breakup happened. The parent passes that point once per revolution. ",
        ...crossings.map((c, i) => h("span", {}, i ? "; " : "", `${c.label.replace("nearest crossing pass to ", "")}: nearest pass ${fmtUTC(c.t)} (${fmtMinutes(c.delta_min ?? null)})`)),
        ". A small offset means that source's time agrees with our breakup location. A reported time can match the geometry while choosing a different revolution than ours.",
      ),
    );
  }
  if (ev.reference_note) panel.append(h("p", { class: "small muted", style: "margin-top:10px" }, ev.reference_note));
  return h("section", { style: "margin-top:8px" }, panel);
}

function minutes(a: string, b: string): number {
  return (new Date(a).getTime() - new Date(b).getTime()) / 60000;
}

function base2(w: number, hgt: number): Record<string, unknown> {
  return { width: w, height: hgt, marginTop: 8, marginBottom: 32, marginRight: 16, style: { background: "transparent", color: "#b9bfca", fontSize: "12px" } };
}

// ===================================================================== solver curves
function solverChart(ev: EventSummary, which: "cross" | "spread", cleanups: (() => void)[]): HTMLElement {
  const sol = ev.solution!;
  const data = (which === "cross" && sol.crossings?.length
    ? sol.crossings.map((d) => ({ t: new Date(d.t), v: d.km as number }))
    : sol.curve!.map((d) => ({ t: new Date(d.t), v: d.spread_km as number }))
  ).filter((d) => d.v !== null && Number.isFinite(d.v));
  const host = h("div", { class: "chart" });
  const refs = ev.references;
  cleanups.push(
    responsive(host, (w) =>
      Plot.plot({
        ...base2(w, 240),
        marginLeft: 52,
        x: { type: "utc", label: null, grid: true },
        y: { type: which === "spread" ? "log" : "linear", label: which === "cross" ? "km to fragment orbits" : "km between objects", grid: true, nice: true },
        marks: [
          sol.t_p05 && sol.t_p95 ? Plot.rectX([0], { x1: new Date(sol.t_p05), x2: new Date(sol.t_p95), fill: C.frag, fillOpacity: 0.08 }) : null,
          Plot.ruleX(refs, { x: (r: Reference) => new Date(r.time), stroke: C.ref, strokeOpacity: 0.8, strokeDasharray: "3,3" }),
          Plot.lineY(data, { x: "t", y: "v", stroke: which === "cross" ? C.parent : C.muted, strokeWidth: 2, curve: "linear" }),
          which === "cross" ? Plot.dot(data, { x: "t", y: "v", r: 3, fill: C.parent }) : null,
          sol.t_p50 ? Plot.ruleX([new Date(sol.t_p50)], { stroke: C.frag, strokeWidth: 2 }) : null,
          Plot.tip(data, Plot.pointerX({ x: "t", y: "v", title: (d: { t: Date; v: number }) => `${fmtUTC(d.t.toISOString())}\n${fmtNum(d.v, 1)} km` })),
        ],
      } as Plot.PlotOptions),
    ),
  );
  return chartPanel({
    title: which === "cross" ? "Orbit-crossing distance" : "Cloud spread (SGP4 back-propagation)",
    subtitle:
      which === "cross"
        ? "Closest approach, once per revolution, of the parent's position to the fragments' orbits (median). Every revolution passes within a few km of the breakup point, so this fixes where in the orbit it happened but only weakly which revolution."
        : "Median parent–fragment distance (log scale). Its broad minimum picks the revolution; along-track error from weeks of back-propagation keeps the floor high.",
    chart: host,
    table: () => dataTable(data.filter((_, i) => i % 4 === 0).map((d) => ({ t: d.t.toISOString(), v: d.v })), [{ key: "t", label: "Time", fmt: (v) => fmtUTC(v as string) }, { key: "v", label: "km", num: true, fmt: (v) => fmtNum(v as number, 1) }]),
    legend: legendItems([{ label: "Our t*", color: C.frag, line: true }, { label: "Reported times", color: C.ref, line: true }, { label: which === "cross" ? "Per-revolution crossing minimum" : "Spread", color: which === "cross" ? C.parent : C.muted, line: true }]),
  });
}

// ===================================================================== parent-only
function parentOnlyPanel(ev: EventSummary, cleanups: (() => void)[]): HTMLElement {
  const po = ev.parent_only!;
  const series = po.series.map((s) => ({ ...s, t: new Date(s.epoch), alt: s.a_km - 6378.137 }));
  const host = h("div", { class: "chart" });
  const recent = series.filter((s) => s.t.getTime() > new Date(ev.reference_time).getTime() - 120 * 86400e3);
  const shown = recent.length >= 2 ? recent : series;
  cleanups.push(
    responsive(host, (w) =>
      Plot.plot({
        ...base2(w, 220),
        marginLeft: 56,
        x: { type: "utc", label: null, grid: true },
        y: { label: "mean altitude (km)", grid: true, nice: true },
        marks: [
          Plot.ruleX([new Date(ev.reference_time)], { stroke: C.ref, strokeDasharray: "3,3" }),
          Plot.lineY(shown, { x: "t", y: "alt", stroke: C.parent, strokeWidth: 2 }),
          Plot.dot(shown, { x: "t", y: "alt", r: 4, fill: C.parent, stroke: "#12161d", strokeWidth: 2, tip: true, title: (d: { t: Date; alt: number; eccentricity: number; bstar: number }) => `${fmtUTC(d.t.toISOString())}\nmean alt ${fmtNum(d.alt, 2)} km\ne ${d.eccentricity.toFixed(6)}\nB* ${d.bstar.toExponential(2)}` }),
        ],
      } as Plot.PlotOptions),
    ),
  );
  const panel = chartPanel({
    title: "Parent-only analysis",
    subtitle: `${po.n_elsets} element set(s) for ${ev.parent.name} in our archive. The dashed line marks the reported event time.`,
    chart: host,
    table: () => dataTable(po.series as unknown as Record<string, unknown>[], [
      { key: "epoch", label: "Epoch", fmt: (v) => fmtUTC(v as string) },
      { key: "mean_motion", label: "Mean motion (rev/d)", num: true, fmt: (v) => (v as number).toFixed(6) },
      { key: "eccentricity", label: "e", num: true, fmt: (v) => (v as number).toFixed(6) },
      { key: "bstar", label: "B*", num: true, fmt: (v) => (v as number).toExponential(3) },
      { key: "a_km", label: "a (km)", num: true, fmt: (v) => fmtNum(v as number, 2) },
    ]),
  });
  const facts = h("div", { class: "row small secondary", style: "margin-top:12px" });
  if (po.window_start || po.window_end) facts.append(h("span", {}, `Event bracketed by element sets ${fmtUTC(po.window_start)} → ${fmtUTC(po.window_end)}.`));
  if (po.dv_t_ms !== null) facts.append(h("span", {}, `Implied along-track Δv of the parent: ${fmtNum(po.dv_t_ms, 2)} m/s.`));
  if (po.changepoints.length) facts.append(h("span", {}, `Changepoints: ${po.changepoints.map((c) => fmtUTC(c.epoch)).join(", ")}.`));
  panel.append(facts);
  if (po.note) panel.append(h("div", { class: "callout warn", style: "margin-top:12px" }, po.note));
  return panel;
}

// ===================================================================== gabbard
function gabbardPanel(rows: GabbardRow[], cleanups: (() => void)[]): HTMLElement {
  const snaps = [...new Set(rows.map((r) => r.snapshot))].sort();
  let idx = snaps.length - 1;
  const host = h("div", { class: "chart" });
  const xs = rows.map((r) => r.period), ys = rows.flatMap((r) => [r.apo, r.peri]);
  const xd = [Math.min(...xs) - 0.2, Math.max(...xs) + 0.2], yd = [Math.max(0, Math.min(...ys) - 20), Math.max(...ys) + 20];
  const label = h("span", { class: "small secondary mono" });
  const slider = h("input", { type: "range", min: "0", max: String(snaps.length - 1), value: String(idx), step: "1", "aria-label": "Gabbard snapshot", style: "flex:1;accent-color:var(--series-2)" }) as HTMLInputElement;
  const playBtn = h("button", { class: "btn", type: "button" }, "▶");
  let lastW = 0;
  const draw = (w: number) => {
    lastW = w;
    const snap = snaps[idx];
    const pts = rows.filter((r) => r.snapshot === snap).flatMap((r) => [{ ...r, kind: "apogee", y: r.apo }, { ...r, kind: "perigee", y: r.peri }]);
    label.textContent = `Snapshot ${fmtDate(snap)} · ${pts.length / 2} objects`;
    return Plot.plot({
      ...base2(w, 300),
      marginLeft: 52,
      x: { domain: xd, label: "Orbital period (min)", grid: true },
      y: { domain: yd, label: "Altitude (km)", grid: true },
      marks: [
        Plot.dot(pts.filter((p) => !p.parent), { x: "period", y: "y", r: 4, symbol: (d: { kind: string }) => (d.kind === "apogee" ? "circle" : "triangle"), fill: C.frag, stroke: "#12161d", strokeWidth: 1.5, tip: true, title: (d: GabbardRow & { kind: string; y: number }) => `NORAD ${d.norad} ${d.kind}\n${fmtNum(d.y)} km, period ${d.period.toFixed(2)} min\nepoch ${fmtUTC(d.epoch)}` }),
        Plot.dot(pts.filter((p) => p.parent), { x: "period", y: "y", r: 7, symbol: (d: { kind: string }) => (d.kind === "apogee" ? "circle" : "triangle"), fill: C.parent, stroke: "#12161d", strokeWidth: 2, tip: true, title: (d: GabbardRow & { kind: string; y: number }) => `Parent ${d.kind}\n${fmtNum(d.y)} km` }),
      ],
    } as Plot.PlotOptions);
  };
  cleanups.push(responsive(host, draw));
  const redraw = () => host.replaceChildren(draw(lastW || host.clientWidth));
  slider.addEventListener("input", () => { idx = Number(slider.value); redraw(); });
  let timer = 0;
  playBtn.addEventListener("click", () => {
    if (timer) { clearInterval(timer); timer = 0; playBtn.textContent = "▶"; return; }
    if (idx >= snaps.length - 1) idx = 0;
    playBtn.textContent = "❚❚";
    timer = window.setInterval(() => {
      idx++;
      slider.value = String(idx);
      redraw();
      if (idx >= snaps.length - 1) { clearInterval(timer); timer = 0; playBtn.textContent = "▶"; }
    }, prefersReducedMotion() ? 1500 : 700);
  });
  cleanups.push(() => clearInterval(timer));
  const panel = chartPanel({
    title: "Gabbard diagram",
    subtitle: "Each object plotted twice at its orbital period: apogee (circle) and perigee (triangle). A fresh breakup makes an X centred on the parent; drag then pulls the low-perigee arm down.",
    chart: host,
    table: () => dataTable(rows.filter((r) => r.snapshot === snaps[idx]) as unknown as Record<string, unknown>[], [
      { key: "norad", label: "NORAD", fmt: (v) => String(v) },
      { key: "period", label: "Period (min)", num: true, fmt: (v) => (v as number).toFixed(2) },
      { key: "apo", label: "Apogee km", num: true, fmt: (v) => fmtNum(v as number) },
      { key: "peri", label: "Perigee km", num: true, fmt: (v) => fmtNum(v as number) },
      { key: "epoch", label: "Element epoch", fmt: (v) => fmtUTC(v as string) },
    ]),
    legend: legendItems([{ label: "Parent", color: C.parent }, { label: "Fragments", color: C.frag }]),
  });
  if (snaps.length > 1) panel.append(h("div", { class: "row", style: "margin-top:10px" }, playBtn, slider, label));
  else panel.append(h("div", { style: "margin-top:8px" }, label));
  return panel;
}

// ===================================================================== Δv
function dvPanel(rows: DvRow[], cleanups: (() => void)[]): HTMLElement {
  const used = rows.filter((r) => (r as DvRow & { used?: boolean }).used !== false);
  const host = h("div", { class: "chart" });
  const comps = used.flatMap((r) => [
    { comp: "Radial", v: r.r },
    { comp: "Transverse", v: r.t },
    { comp: "Normal", v: r.n },
  ]);
  const lim = Math.max(10, ...used.flatMap((r) => [Math.abs(r.r), Math.abs(r.t), Math.abs(r.n)])) * 1.1;
  let view: "scatter" | "hist" = "scatter";
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Δv view" });
  const b1 = h("button", { type: "button", "aria-pressed": "true" }, "T vs R");
  const b2 = h("button", { type: "button", "aria-pressed": "false" }, "RTN histograms");
  seg.append(b1, b2);
  let lastW = 0;
  const draw = (w: number) => {
    lastW = w;
    if (view === "scatter") {
      return Plot.plot({
        ...base2(w, 300),
        marginLeft: 52,
        aspectRatio: undefined,
        x: { domain: [-lim, lim], label: "Radial Δv (m/s)", grid: true },
        y: { domain: [-lim, lim], label: "Transverse (along-track) Δv (m/s)", grid: true },
        r: { range: [3, 9] },
        marks: [
          Plot.ruleX([0], { stroke: "#3a4150" }),
          Plot.ruleY([0], { stroke: "#3a4150" }),
          Plot.dot(used, { x: "r", y: "t", r: "mag", fill: C.frag, fillOpacity: 0.9, stroke: "#12161d", strokeWidth: 1.5, tip: true, title: (d: DvRow) => `NORAD ${d.norad}\n|Δv| ${fmtNum(d.mag, 1)} m/s\nR ${fmtNum(d.r, 1)} · T ${fmtNum(d.t, 1)} · N ${fmtNum(d.n, 1)}\norbit miss ${fmtNum(d.residual_km, 1)} km` }),
        ],
      } as Plot.PlotOptions);
    }
    return Plot.plot({
      ...base2(w, 300),
      marginLeft: 40,
      fx: { label: null, domain: ["Radial", "Transverse", "Normal"] },
      x: { label: "Δv component (m/s)", domain: [-lim, lim] },
      y: { label: "fragments", grid: true },
      marks: [
        Plot.rectY(comps, Plot.binX({ y: "count" }, { x: "v", fx: "comp", fill: C.frag, thresholds: 12, inset: 1 } as Record<string, unknown>)),
        Plot.ruleY([0], { stroke: "#3a4150" }),
      ],
    } as Plot.PlotOptions);
  };
  cleanups.push(responsive(host, draw));
  const set = (v: "scatter" | "hist") => {
    view = v;
    b1.setAttribute("aria-pressed", String(v === "scatter"));
    b2.setAttribute("aria-pressed", String(v === "hist"));
    host.replaceChildren(draw(lastW || host.clientWidth));
  };
  b1.addEventListener("click", () => set("scatter"));
  b2.addEventListener("click", () => set("hist"));
  const n = rows.length - used.length;
  return chartPanel({
    title: "Velocity kicks (Δv)",
    subtitle: `Dot size is |Δv|. Each fragment's velocity relative to the parent at the breakup point, in the parent's radial / transverse / normal frame. ${used.length} reliable fragment(s)${n ? `; ${n} excluded (orbit misses the point or was an outlier)` : ""}.`,
    chart: host,
    extra: seg,
    table: () => dataTable(rows as unknown as Record<string, unknown>[], [
      { key: "norad", label: "NORAD", fmt: (v) => String(v) },
      { key: "r", label: "R m/s", num: true, fmt: (v) => fmtNum(v as number, 1) },
      { key: "t", label: "T m/s", num: true, fmt: (v) => fmtNum(v as number, 1) },
      { key: "n", label: "N m/s", num: true, fmt: (v) => fmtNum(v as number, 1) },
      { key: "mag", label: "|Δv| m/s", num: true, fmt: (v) => fmtNum(v as number, 1) },
      { key: "residual_km", label: "Orbit miss km", num: true, fmt: (v) => fmtNum(v as number, 1) },
      { key: "used", label: "Used", fmt: (v) => (v === false ? "no" : "yes") },
    ], { sortable: true }),
  });
}

// ===================================================================== membership
function membershipPanel(ev: EventSummary, cleanups: (() => void)[]): HTMLElement {
  const m = ev.membership;
  const counts = m.counts as Record<string, number>;
  const steps = [
    ["Share the designator", counts.intdes_candidates],
    ["Already reentered", counts.decayed_before_event],
    ["Catalogued after the event", counts.pass_time_filter],
    ["In the parent's plane cluster", counts.cluster_confirmed],
    ["Counted as fragments", counts.members],
  ] as const;
  const funnel = h("div", { class: "kpis", style: "margin-bottom:14px;gap:20px" }, ...steps.filter(([, v]) => v !== undefined).map(([k, v]) => h("div", {}, h("div", { class: "k" }, k), h("div", { class: "v" }, fmtNum(v)))));
  const host = h("div", { class: "chart" });
  const pts = m.clusters;
  if (pts.length > 1) {
    cleanups.push(
      responsive(host, (w) =>
        Plot.plot({
          ...base2(w, 260),
          marginLeft: 52,
          x: { label: "RAAN relative to parent (deg)", grid: true },
          y: { label: "Inclination (deg)", grid: true, nice: true },
          marks: [
            Plot.dot(pts.filter((p) => p.assignment !== "parent"), {
              x: "x", y: "y", r: 5, symbol: (d: { in_event: boolean }) => (d.in_event ? "circle" : "times"),
              stroke: (d: { in_event: boolean }) => (d.in_event ? "#12161d" : C.prior), fill: (d: { in_event: boolean }) => (d.in_event ? C.frag : "none"), strokeWidth: (d: { in_event: boolean }) => (d.in_event ? 1.5 : 2),
              tip: true, title: (d: { name: string; norad: number; assignment: string; first_epoch: string | null; label: number }) => `${d.name} (${d.norad})\n${d.assignment}\ncluster ${d.label}\nfirst catalogued ${fmtDate(d.first_epoch)}`,
            }),
            Plot.dot(pts.filter((p) => p.assignment === "parent"), { x: "x", y: "y", r: 8, fill: C.parent, stroke: "#12161d", strokeWidth: 2, tip: true, title: () => "Parent" }),
          ],
        } as Plot.PlotOptions),
      ),
    );
  } else host.append(h("p", { class: "muted small" }, "No catalogued debris to cluster."));
  const panel = chartPanel({
    title: "Membership: why these objects count",
    subtitle: m.explain,
    chart: host,
    table: () => dataTable(pts as unknown as Record<string, unknown>[], [
      { key: "norad", label: "NORAD", fmt: (v) => String(v) },
      { key: "name", label: "Name" },
      { key: "assignment", label: "Decision" },
      { key: "label", label: "Cluster", num: true },
      { key: "x", label: "ΔRAAN°", num: true, fmt: (v) => fmtNum(v as number, 2) },
      { key: "inc", label: "Inc°", num: true, fmt: (v) => fmtNum(v as number, 3) },
      { key: "first_epoch", label: "First catalogued", fmt: (v) => fmtDate(v as string) },
    ], { sortable: true }),
    legend: legendItems([{ label: "Parent", color: C.parent }, { label: "Counted fragment", color: C.frag }, { label: "Excluded (older debris)", color: C.prior, ring: true }]),
  });
  panel.querySelector(".panel-head")!.after(funnel);
  return panel;
}

// ===================================================================== decay curve
function decayPanel(ev: EventSummary, cleanups: (() => void)[]): HTMLElement {
  const data = ev.decay_curve.map((d) => ({ ...d, t: new Date(d.date) }));
  const host = h("div", { class: "chart" });
  const n = ev.fragments.length;
  cleanups.push(
    responsive(host, (w) =>
      Plot.plot({
        ...base2(w, 260),
        marginLeft: 44,
        x: { type: "utc", label: null, grid: true },
        y: { label: "fragments in orbit", grid: true, domain: [0, Math.max(n, 1)] },
        marks: [
          Plot.areaY(data, { x: "t", y: "remaining", fill: C.frag, fillOpacity: 0.1, curve: "step-after" }),
          Plot.lineY(data, { x: "t", y: "remaining", stroke: C.frag, strokeWidth: 2, curve: "step-after" }),
          Plot.lineY(data, { x: "t", y: "catalogued", stroke: C.muted, strokeWidth: 1.5, strokeDasharray: "4,3", curve: "step-after" }),
          Plot.tip(data, Plot.pointerX({ x: "t", y: "remaining", title: (d: { t: Date; remaining: number; catalogued: number }) => `${fmtDate(d.t.toISOString())}\n${d.remaining} in orbit\n${d.catalogued} catalogued so far` })),
        ],
      } as Plot.PlotOptions),
    ),
  );
  return chartPanel({
    title: "Reentry curve",
    subtitle: "Fragments still in orbit (solid) vs fragments catalogued so far (dashed). Decay dates are day-precision SATCAT labels.",
    chart: host,
    table: () => dataTable(ev.decay_curve as unknown as Record<string, unknown>[], [{ key: "date", label: "Date" }, { key: "remaining", label: "In orbit", num: true }, { key: "catalogued", label: "Catalogued", num: true }]),
    legend: legendItems([{ label: "In orbit", color: C.frag, line: true }, { label: "Catalogued", color: C.muted, line: true }]),
  });
}
