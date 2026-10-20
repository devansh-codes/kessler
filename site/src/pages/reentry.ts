import { api } from "../api";
import type { Backtest, ForecastRow, SpaceWeather } from "../types";
import { chartPanel, dataTable, errorBox, fmtDate, fmtNum, fmtUTC, h, loading } from "../ui";
import { C, legendItems, Plot, responsive } from "../viz/plot";

const DAY = 86400e3;

export async function render(root: HTMLElement): Promise<() => void> {
  const wrap = h("div", { class: "wrap" });
  root.append(wrap);
  wrap.append(loading("Loading forecasts…"));
  const cleanups: (() => void)[] = [];
  let fc: ForecastRow[] = [], bt: Backtest, sw: SpaceWeather | null = null;
  try {
    [fc, bt] = await Promise.all([api.forecasts(), api.backtest()]);
    sw = await api.spaceweather().catch(() => null);
  } catch (e) {
    wrap.replaceChildren(h("div", { class: "section" }, errorBox(e)));
    return () => undefined;
  }
  wrap.replaceChildren();
  const now = Date.now();
  const model = bt.metrics.find((m) => m.model.startsWith("Quantile GBM +"));
  const base = bt.metrics.find((m) => m.model === "Physics baseline");

  wrap.append(
    h(
      "header",
      { class: "event-head stack" },
      h("p", { class: "eyebrow" }, "Reentry Watch"),
      h("h1", {}, "When will it come down?"),
      h(
        "p",
        { class: "lede" },
        "Probabilistic reentry dates for decaying debris, rocket bodies and unidentified objects, including fragments from the events on this site. Payloads are excluded because many are deorbited under control. A gradient-boosted quantile model, recalibrated with split-conformal prediction, beats a drag-physics baseline. Every forecast is archived and scored automatically once the object falls.",
      ),
    ),
    h(
      "section",
      { class: "grid grid-4", style: "margin-top:24px" },
      tile("Objects under watch", fmtNum(fc.length), `issued ${fc.length ? fmtUTC(fc[0].issued_at) : "—"}`),
      tile("Model error (holdout)", model ? `${fmtNum(model.mae_days, 1)} days` : "—", base ? `physics baseline: ${fmtNum(base.mae_days, 1)} days · skill ${fmtNum((model?.skill_vs_baseline ?? 0) * 100, 0)}%` : ""),
      tile("80% interval coverage", model ? `${fmtNum(model.coverage80 * 100, 0)}%` : "—", "target 80% · split-conformal"),
      tile("Live forecasts scored", bt.live_summary ? fmtNum(bt.live_summary.n) : "0", bt.live_summary ? `MAE ${fmtNum(bt.live_summary.mae_days, 1)} d · coverage ${fmtNum(bt.live_summary.coverage80 * 100, 0)}%` : "scored automatically after each reentry"),
    ),
  );

  // ------------------------------------------------------------ upcoming reentries chart
  const soon = fc.filter((f) => new Date(f.p50).getTime() < now + 90 * DAY).slice(0, 40);
  const chartHost = h("div", { class: "chart" });
  if (soon.length) {
    cleanups.push(
      responsive(chartHost, (w) =>
        Plot.plot({
          width: w,
          height: 40 + soon.length * 18,
          marginLeft: Math.min(200, w * 0.36),
          marginRight: 20,
          marginBottom: 30,
          style: { background: "transparent", color: "#b9bfca", fontSize: "11.5px" },
          x: { type: "utc", grid: true, label: null, domain: [new Date(now - 2 * DAY), new Date(Math.min(now + 100 * DAY, Math.max(...soon.map((f) => new Date(f.p90).getTime())) + 3 * DAY))], clamp: true },
          y: { domain: soon.map((f) => label(f)), label: null, tickFormat: (s: string) => (s.length > 28 ? s.slice(0, 27) + "…" : s) },
          marks: [
            Plot.ruleX([new Date(now)], { stroke: "#838b99", strokeDasharray: "2,3" }),
            Plot.ruleY(soon, { y: label, x1: (f: ForecastRow) => new Date(f.p10), x2: (f: ForecastRow) => new Date(f.p90), stroke: (f: ForecastRow) => (f.event_id ? C.frag : C.parent), strokeWidth: 6, strokeOpacity: 0.35, strokeLinecap: "round" }),
            Plot.tickX(soon.filter((f) => f.baseline && new Date(f.baseline).getTime() < now + 100 * DAY), { y: label, x: (f: ForecastRow) => new Date(f.baseline!), stroke: C.ref, strokeWidth: 2 }),
            Plot.dot(soon, { y: label, x: (f: ForecastRow) => new Date(f.p50), r: 4.5, fill: (f: ForecastRow) => (f.event_id ? C.frag : C.parent), stroke: "#12161d", strokeWidth: 2, tip: true, title: (f: ForecastRow) => `${f.name} (${f.norad})\n${f.object_type}${f.event_id ? ` · event ${f.event_id}` : ""}\nperigee ${fmtNum(f.perigee_km)} km\nmedian ${fmtDate(f.p50)}\n80%: ${fmtDate(f.p10)} → ${fmtDate(f.p90)}\nbaseline ${fmtDate(f.baseline)}` }),
          ],
        } as Plot.PlotOptions),
      ),
    );
  } else chartHost.append(h("p", { class: "muted" }, "No forecasts within the next 90 days."));
  wrap.append(
    h(
      "section",
      { style: "margin-top:16px" },
      chartPanel({
        title: "Next reentries",
        subtitle: "Median forecast (dot) with 80% interval (bar), soonest first. The yellow tick is the physics baseline.",
        chart: chartHost,
        legend: legendItems([{ label: "Event fragment", color: C.frag }, { label: "Other decaying object", color: C.parent }, { label: "Physics baseline", color: C.ref, line: true }]),
        table: () => forecastTable(soon),
      }),
    ),
  );

  // ------------------------------------------------------------ calibration + lead time
  const row = h("section", { class: "grid grid-2", style: "margin-top:16px" });
  row.append(calibrationPanel(bt, cleanups), leadPanel(bt, cleanups));
  wrap.append(row);

  // ------------------------------------------------------------ space weather
  if (sw && sw.daily.length) wrap.append(h("section", { style: "margin-top:16px" }, spaceWeatherPanel(sw, cleanups)));

  // ------------------------------------------------------------ tables
  wrap.append(
    h(
      "section",
      { class: "panel", style: "margin-top:16px" },
      h("div", { class: "panel-head" }, h("h2", {}, "All active forecasts"), h("p", {}, `${fc.length} objects. Sort by any column.`)),
      forecastTable(fc),
    ),
  );
  if (bt.scored_live.length) {
    wrap.append(
      h(
        "section",
        { class: "panel", style: "margin-top:16px" },
        h("div", { class: "panel-head" }, h("h2", {}, "Scorecard of our own past forecasts"), h("p", {}, "Forecasts issued in earlier runs, scored against the SATCAT decay date.")),
        dataTable(bt.scored_live.slice().reverse() as unknown as Record<string, unknown>[], [
          { key: "name", label: "Object" },
          { key: "issued_at", label: "Issued", fmt: (v) => fmtUTC(v as string) },
          { key: "lead_days", label: "Lead (d)", num: true, fmt: (v) => fmtNum(v as number, 1) },
          { key: "p50", label: "Forecast", fmt: (v) => fmtDate(v as string) },
          { key: "actual", label: "Actual", fmt: (v) => fmtDate(v as string) },
          { key: "abs_err_days", label: "Error (d)", num: true, fmt: (v) => fmtNum(v as number, 1) },
          { key: "inside80", label: "In 80%?", fmt: (v) => (v ? "yes" : "no") },
        ], { sortable: true }),
      ),
    );
  }
  wrap.append(
    h(
      "section",
      { class: "callout", style: "margin:16px 0 48px" },
      h("strong", {}, "How to read this. "),
      `Backtest: ${fmtNum(bt.n_train)} training, ${fmtNum(bt.n_calibration ?? 0)} calibration and ${fmtNum(bt.n_holdout)} holdout element sets from ${fmtNum(bt.objects ?? 0)} reentered objects, split in time order. Holdout begins ${fmtDate(bt.holdout_start)}. `,
      ...bt.notes.map((n) => h("span", {}, n + " ")),
    ),
  );
  return () => cleanups.forEach((c) => c());
}

function label(f: ForecastRow): string {
  return `${f.name} · ${f.norad}`;
}

function tile(l: string, v: string, s: string): HTMLElement {
  return h("div", { class: "tile" }, h("div", { class: "label" }, l), h("div", { class: "value" }, v), h("div", { class: "sub" }, s));
}

function forecastTable(rows: ForecastRow[]): HTMLElement {
  const now = Date.now();
  const data = rows.map((f) => ({ ...f, days: (new Date(f.p50).getTime() - now) / DAY }));
  return dataTable(data as unknown as Record<string, unknown>[], [
    { key: "name", label: "Object" },
    { key: "norad", label: "NORAD", num: true, fmt: (v) => String(v) },
    { key: "object_type", label: "Type" },
    { key: "event_id", label: "Event", fmt: (v) => (v ? h("a", { href: `#/event/${v}` }, String(v)) : "—") },
    { key: "perigee_km", label: "Perigee km", num: true, fmt: (v) => fmtNum(v as number) },
    { key: "p10", label: "10%", fmt: (v) => fmtDate(v as string) },
    { key: "p50", label: "Median", fmt: (v) => fmtDate(v as string) },
    { key: "p90", label: "90%", fmt: (v) => fmtDate(v as string) },
    { key: "days", label: "Days to median", num: true, fmt: (v) => fmtNum(v as number, 1) },
    { key: "baseline", label: "Baseline", fmt: (v) => fmtDate(v as string) },
  ], { sortable: true, initialSort: { key: "days", dir: 1 } });
}

function calibrationPanel(bt: Backtest, cleanups: (() => void)[]): HTMLElement {
  const host = h("div", { class: "chart" });
  const d = bt.calibration;
  cleanups.push(
    responsive(host, (w) =>
      Plot.plot({
        width: w,
        height: 280,
        marginLeft: 52,
        marginBottom: 40,
        style: { background: "transparent", color: "#b9bfca", fontSize: "12px" },
        x: { domain: [0.4, 1], label: "Nominal coverage", tickFormat: "%", grid: true },
        y: { domain: [0, 1], label: "Empirical coverage (holdout)", tickFormat: "%", grid: true },
        marks: [
          Plot.line([[0.4, 0.4], [1, 1]], { stroke: "#3a4150", strokeDasharray: "4,4" }),
          Plot.line(d.filter((r) => r.model === "raw"), { x: "nominal", y: "empirical", stroke: C.muted, strokeWidth: 2 }),
          Plot.dot(d.filter((r) => r.model === "raw"), { x: "nominal", y: "empirical", r: 5, fill: C.muted, stroke: "#12161d", strokeWidth: 2, tip: true }),
          Plot.line(d.filter((r) => r.model === "conformal"), { x: "nominal", y: "empirical", stroke: C.prior, strokeWidth: 2 }),
          Plot.dot(d.filter((r) => r.model === "conformal"), { x: "nominal", y: "empirical", r: 5, fill: C.prior, stroke: "#12161d", strokeWidth: 2, tip: true }),
        ],
      } as Plot.PlotOptions),
    ),
  );
  return chartPanel({
    title: "Calibration",
    subtitle: "Do the 50/80/90% intervals contain the truth that often? On the diagonal is perfect. Conformal recalibration pulls the raw quantile model onto it.",
    chart: host,
    legend: legendItems([{ label: "Conformal", color: C.prior }, { label: "Raw quantiles", color: C.muted }]),
    table: () => dataTable(d as unknown as Record<string, unknown>[], [{ key: "model", label: "Model" }, { key: "nominal", label: "Nominal", num: true, fmt: (v) => `${fmtNum((v as number) * 100, 0)}%` }, { key: "empirical", label: "Empirical", num: true, fmt: (v) => `${fmtNum((v as number) * 100, 1)}%` }]),
  });
}

function leadPanel(bt: Backtest, cleanups: (() => void)[]): HTMLElement {
  const host = h("div", { class: "chart" });
  const d = bt.lead_time.flatMap((r) => [
    { bin: r.days_before, mae: r.mae_days, model: "Model" },
    { bin: r.days_before, mae: r.baseline_mae_days, model: "Baseline" },
  ]);
  cleanups.push(
    responsive(host, (w) =>
      Plot.plot({
        width: w,
        height: 280,
        marginLeft: 52,
        marginBottom: 40,
        style: { background: "transparent", color: "#b9bfca", fontSize: "12px" },
        x: { type: "log", label: "Days before reentry (bin upper edge)", grid: true, ticks: [1, 3, 7, 14, 30, 60, 120], tickFormat: (v: number) => String(v) },
        y: { type: "log", label: "Mean absolute error (days)", grid: true },
        marks: [
          Plot.line(d, { x: "bin", y: "mae", stroke: (r: { model: string }) => (r.model === "Model" ? C.prior : C.ref), strokeWidth: 2 }),
          Plot.dot(d, { x: "bin", y: "mae", r: 4.5, fill: (r: { model: string }) => (r.model === "Model" ? C.prior : C.ref), stroke: "#12161d", strokeWidth: 2, tip: true, title: (r: { bin: number; mae: number; model: string }) => `${r.model}\n≤ ${r.bin} days out\nMAE ${fmtNum(r.mae, 2)} d` }),
        ],
      } as Plot.PlotOptions),
    ),
  );
  const m = bt.metrics.find((x) => x.model.startsWith("Quantile GBM +"));
  return chartPanel({
    title: "Error by lead time",
    subtitle: `How far ahead is the forecast useful? Median lead time over which the 80% interval keeps containing the truth: ${m?.median_lead_days != null ? fmtNum(m.median_lead_days, 1) + " days" : "—"}.`,
    chart: host,
    legend: legendItems([{ label: "Quantile model", color: C.prior }, { label: "Physics baseline", color: C.ref }]),
    table: () => dataTable(bt.lead_time as unknown as Record<string, unknown>[], [
      { key: "days_before", label: "≤ days out", num: true },
      { key: "n", label: "Rows", num: true },
      { key: "mae_days", label: "Model MAE (d)", num: true, fmt: (v) => fmtNum(v as number, 2) },
      { key: "baseline_mae_days", label: "Baseline MAE (d)", num: true, fmt: (v) => fmtNum(v as number, 2) },
      { key: "coverage", label: "80% coverage", num: true, fmt: (v) => `${fmtNum((v as number) * 100, 0)}%` },
    ]),
  });
}

function spaceWeatherPanel(sw: SpaceWeather, cleanups: (() => void)[]): HTMLElement {
  const obs = sw.daily.filter((d) => d.type !== "PRD" && d.type !== "PRM").map((d) => ({ ...d, t: new Date(d.date) }));
  const storms = obs.filter((d) => (d.kp_max ?? 0) >= 5);
  const top = h("div", { class: "chart" });
  const bottom = h("div", { class: "chart" });
  const xDomain = [obs[0]?.t ?? new Date(), obs[obs.length - 1]?.t ?? new Date()];
  const stormMark = (y2: number) => Plot.rectX(storms, { x1: (d: { t: Date }) => d.t, x2: (d: { t: Date }) => new Date(d.t.getTime() + DAY), y1: 0, y2, fill: C.critical, fillOpacity: 0.12 });
  cleanups.push(
    responsive(top, (w) =>
      Plot.plot({
        width: w, height: 170, marginLeft: 52, marginBottom: 20,
        style: { background: "transparent", color: "#b9bfca", fontSize: "12px" },
        x: { type: "utc", domain: xDomain, label: null, grid: true, axis: null },
        y: { label: "F10.7 (sfu)", grid: true, domain: [0, Math.max(...obs.map((d) => d.f107 ?? 0)) * 1.05] },
        marks: [
          stormMark(400),
          Plot.lineY(obs, { x: "t", y: "f107", stroke: C.ref, strokeWidth: 1, strokeOpacity: 0.7 }),
          Plot.lineY(obs, { x: "t", y: "f107_81", stroke: C.ref, strokeWidth: 2.5 }),
          Plot.tip(obs, Plot.pointerX({ x: "t", y: "f107", title: (d: { date: string; f107: number; f107_81: number }) => `${d.date}\nF10.7 ${fmtNum(d.f107, 1)}\n81-day ${fmtNum(d.f107_81, 1)}` })),
        ],
      } as Plot.PlotOptions),
    ),
    responsive(bottom, (w) =>
      Plot.plot({
        width: w, height: 150, marginLeft: 52, marginBottom: 30,
        style: { background: "transparent", color: "#b9bfca", fontSize: "12px" },
        x: { type: "utc", domain: xDomain, label: null, grid: true },
        y: { label: "Daily max Kp", grid: true, domain: [0, 9] },
        marks: [
          stormMark(9),
          Plot.rectY(obs, { x1: (d: { t: Date }) => d.t, x2: (d: { t: Date }) => new Date(d.t.getTime() + DAY * 0.8), y: "kp_max", fill: (d: { kp_max: number }) => ((d.kp_max ?? 0) >= 5 ? C.critical : C.parent), fillOpacity: 0.85 }),
          Plot.ruleY([5], { stroke: C.critical, strokeDasharray: "3,3", strokeOpacity: 0.7 }),
          Plot.tip(obs, Plot.pointerX({ x: "t", y: "kp_max", title: (d: { date: string; kp_max: number; ap: number }) => `${d.date}\nmax Kp ${fmtNum(d.kp_max, 1)}\nAp ${fmtNum(d.ap, 0)}` })),
        ],
      } as Plot.PlotOptions),
    ),
  );
  const chart = h("div", {}, top, bottom);
  const live = sw.kp_live.length ? sw.kp_live[sw.kp_live.length - 1] : null;
  return chartPanel({
    title: "Space weather",
    subtitle: `Solar flux heats and expands the upper atmosphere, and geomagnetic storms (Kp ≥ 5, shaded) spike drag. Last 400 days of observations.${live ? ` Latest NOAA Kp: ${fmtNum(live.kp, 2)} at ${fmtUTC(live.t)}.` : ""}`,
    chart,
    legend: legendItems([{ label: "F10.7 daily", color: C.ref, line: true }, { label: "F10.7 81-day mean", color: C.ref, line: true }, { label: "Kp (storm ≥ 5)", color: C.critical }]),
    table: () => dataTable(obs.slice(-120).reverse() as unknown as Record<string, unknown>[], [
      { key: "date", label: "Date" },
      { key: "f107", label: "F10.7", num: true, fmt: (v) => fmtNum(v as number, 1) },
      { key: "f107_81", label: "81-day", num: true, fmt: (v) => fmtNum(v as number, 1) },
      { key: "ap", label: "Ap", num: true, fmt: (v) => fmtNum(v as number, 0) },
      { key: "kp_max", label: "Max Kp", num: true, fmt: (v) => fmtNum(v as number, 1) },
    ]),
  });
}
