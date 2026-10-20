import { api } from "../api";
import type { Scorecard, ScorecardRow } from "../types";
import { chartPanel, dataTable, errorBox, fmtDate, fmtNum, h, loading } from "../ui";
import { C, legendItems, Plot, responsive } from "../viz/plot";

export async function render(root: HTMLElement): Promise<() => void> {
  const wrap = h("div", { class: "wrap" });
  root.append(wrap);
  wrap.append(loading("Loading scorecard…"));
  let sc: Scorecard;
  try {
    sc = await api.scorecard();
  } catch (e) {
    wrap.replaceChildren(h("div", { class: "section" }, errorBox(e)));
    return () => undefined;
  }
  wrap.replaceChildren();
  const cleanups: (() => void)[] = [];
  let metric: "stage_debris" | "debris_per_launch" = "debris_per_launch";
  let scope: "all" | "recent" = "all";

  const lm6a = sc.rows.find((r) => r.family === "Long March 6A");
  const f9 = sc.rows.find((r) => r.family === "Falcon 9");
  wrap.append(
    h(
      "header",
      { class: "event-head stack" },
      h("p", { class: "eyebrow" }, "Rocket Stage Scorecard"),
      h("h1", {}, "Which rockets leave the most debris behind?"),
      h(
        "p",
        { class: "lede" },
        "Upper stages that stay in orbit with leftover propellant or pressurant can explode years later. We count catalogued debris whose catalog parent is a rocket stage, by launch-vehicle family.",
      ),
    ),
  );
  if (lm6a && f9) {
    wrap.append(
      h(
        "section",
        { class: "grid grid-3", style: "margin-top:24px" },
        h("div", { class: "tile" }, h("div", { class: "label" }, "Long March 6A"), h("div", { class: "value" }, `${fmtNum(lm6a.debris_per_launch, 1)} pieces per launch`), h("div", { class: "sub" }, `${fmtNum(lm6a.stage_debris)} stage debris from ${lm6a.launches} launches · ${lm6a.frag_events} stage breakups`)),
        h("div", { class: "tile" }, h("div", { class: "label" }, "Falcon 9"), h("div", { class: "value" }, `${fmtNum(f9.debris_per_launch, 2)} pieces per launch`), h("div", { class: "sub" }, `${fmtNum(f9.stage_debris)} stage debris from ${fmtNum(f9.launches)} launches; second stages are mostly deorbited`)),
        h("div", { class: "tile" }, h("div", { class: "label" }, "Ratio"), h("div", { class: "value" }, `${fmtNum((lm6a.debris_per_launch ?? 0) / Math.max(f9.debris_per_launch ?? 1e-9, 1e-9), 0)}×`), h("div", { class: "sub" }, "more catalogued stage debris per launch")),
      ),
    );
  }

  const host = h("div", { class: "chart" });
  const segM = h("div", { class: "seg", role: "group", "aria-label": "Metric" });
  const segS = h("div", { class: "seg", role: "group", "aria-label": "Time range" });
  const mk = (seg: HTMLElement, label: string, on: boolean, fn: () => void) => {
    const b = h("button", { type: "button", "aria-pressed": String(on) }, label);
    b.addEventListener("click", () => {
      seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", "false"));
      b.setAttribute("aria-pressed", "true");
      fn();
      redraw();
    });
    seg.append(b);
  };
  mk(segM, "Per launch", true, () => (metric = "debris_per_launch"));
  mk(segM, "Total debris", false, () => (metric = "stage_debris"));
  mk(segS, "All time", true, () => (scope = "all"));
  mk(segS, `Launched since ${sc.since_year}`, false, () => (scope = "recent"));

  let lastW = 0;
  const rows = () => (scope === "all" ? sc.rows : sc.rows_recent).filter((r) => metric === "stage_debris" || r.launches >= 5);
  const draw = (w: number) => {
    lastW = w;
    const data = [...rows()].sort((a, b) => ((b[metric] ?? 0) as number) - ((a[metric] ?? 0) as number)).slice(0, 24);
    return Plot.plot({
      width: w,
      height: 40 + data.length * 24,
      marginLeft: Math.min(150, w * 0.3),
      marginRight: 56,
      marginBottom: 30,
      style: { background: "transparent", color: "#b9bfca", fontSize: "12px" },
      x: { label: metric === "stage_debris" ? "Catalogued debris from rocket stages" : "Stage debris per orbital launch", grid: true },
      y: { domain: data.map((d) => d.family), label: null },
      marks: [
        Plot.barX(data, { y: "family", x: metric, fill: (d: ScorecardRow) => (d.highlight ? C.frag : C.parent), fillOpacity: (d: ScorecardRow) => (d.highlight ? 1 : 0.75), insetTop: 3, insetBottom: 3, rx: 3, tip: true, title: (d: ScorecardRow) => `${d.family}\n${fmtNum(d.launches)} orbital launches\n${fmtNum(d.stage_debris)} stage debris (${fmtNum(d.stage_debris_in_orbit)} still in orbit)\n${fmtNum(d.debris_per_launch, 2)} per launch\n${d.frag_events} stage breakups\nrocket bodies in orbit: ${fmtNum(d.rb_in_orbit)}` }),
        Plot.text(data, { y: "family", x: metric, text: (d: ScorecardRow) => fmtNum(d[metric] as number, metric === "stage_debris" ? 0 : 1), textAnchor: "start", dx: 6, fill: "#b9bfca" }),
        Plot.ruleX([0], { stroke: "#3a4150" }),
      ],
    } as Plot.PlotOptions);
  };
  cleanups.push(responsive(host, draw));
  const redraw = () => host.replaceChildren(draw(lastW || host.clientWidth));
  wrap.append(
    h(
      "section",
      { style: "margin-top:16px" },
      chartPanel({
        title: "Debris by launch-vehicle family",
        subtitle: "Per-launch rates are shown for families with at least 5 orbital launches.",
        chart: host,
        extra: h("div", { class: "row" }, segM, segS),
        legend: legendItems([{ label: "Highlighted: Long March 6A/6C, Falcon 9", color: C.frag }, { label: "Other families", color: C.parent }]),
        table: () =>
          dataTable((scope === "all" ? sc.rows : sc.rows_recent) as unknown as Record<string, unknown>[], [
            { key: "family", label: "Family" },
            { key: "launches", label: "Orbital launches", num: true },
            { key: "rb_total", label: "Stages catalogued", num: true },
            { key: "rb_in_orbit", label: "Stages in orbit", num: true },
            { key: "stage_debris", label: "Stage debris", num: true },
            { key: "stage_debris_in_orbit", label: "…in orbit", num: true },
            { key: "debris_per_launch", label: "Per launch", num: true, fmt: (v) => fmtNum(v as number, 2) },
            { key: "frag_events", label: "Stage breakups", num: true },
            { key: "median_days_to_first_debris", label: "Median days to first debris", num: true, fmt: (v) => fmtNum(v as number, 0) },
          ], { sortable: true }),
      }),
    ),
  );

  wrap.append(
    h(
      "section",
      { class: "panel", style: "margin-top:16px" },
      h("div", { class: "panel-head" }, h("h2", {}, "Rocket-stage breakups"), h("p", {}, `Stages with at least ${sc.frag_min} catalogued debris pieces, most recent first. Date = earliest debris separation date in GCAT.`)),
      dataTable(sc.events as unknown as Record<string, unknown>[], [
        { key: "date", label: "First debris", fmt: (v) => fmtDate(v as string) },
        { key: "name", label: "Stage" },
        { key: "family", label: "Family" },
        { key: "pieces", label: "Pieces", num: true },
        { key: "launch_tag", label: "Launch" },
      ], { sortable: true }),
    ),
    h(
      "section",
      { class: "callout", style: "margin:16px 0 48px" },
      h("strong", {}, "Data and citation. "),
      sc.citation,
      ". Licensed CC-BY 4.0. A breakup is counted when a stage has at least ",
      String(sc.frag_min),
      " catalogued pieces. This proxy misses breakups whose debris was never catalogued, and over-counts stages that shed many small parts.",
    ),
  );
  return () => cleanups.forEach((c) => c());
}
