import { api, DataMissing } from "../api";
import type { EventIndexEntry } from "../types";
import { errorBox, flagBadge, fmtMinutes, fmtNum, fmtUTC, h, prefersReducedMotion, svgEl } from "../ui";

export async function render(root: HTMLElement): Promise<() => void> {
  const globeHost = h("div", { class: "hero-globe", "aria-hidden": "true" });
  const kpis = h("div", { class: "kpis" });
  const hero = h(
    "section",
    { class: "hero" },
    h(
      "div",
      { class: "wrap hero-inner" },
      h(
        "div",
        { class: "hero-copy" },
        h(
          "div",
          { class: "stack-lg" },
          h("p", { class: "eyebrow" }, "Orbital breakup forensics · 2026"),
          h("h1", {}, "Kessler: reconstructing 2026's orbital breakups from public data"),
          h(
            "p",
            { class: "lede" },
            "For each fragmentation we estimate when and where the object came apart, how hard each piece was kicked, and when the debris will fall back to Earth. We use only public CelesTrak element sets, with no proprietary tracking.",
          ),
          kpis,
          h("div", { class: "row" }, h("a", { class: "btn primary", href: "#board" }, "See the breakups"), h("a", { class: "btn", href: "#/methods" }, "How it works")),
        ),
      ),
      globeHost,
    ),
  );
  const board = h("div", { class: "board", id: "board-grid" });
  const boardSection = h(
    "section",
    { class: "wrap section", id: "board" },
    h("div", { class: "panel-head" }, h("div", {}, h("p", { class: "eyebrow" }, "Breakup Board"), h("h2", { style: "margin-top:6px" }, "Reconstructed events")), h("p", {}, "Times are our median estimate with a 90% interval. The badge compares them with the independently reported time.")),
    board,
  );
  const explore = h(
    "section",
    { class: "wrap section", style: "padding-top:0" },
    h("p", { class: "eyebrow", style: "margin-bottom:14px" }, "Explore"),
    h(
      "div",
      { class: "grid grid-3" },
      link("#/reentry", "Reentry Watch", "Probabilistic reentry dates for decaying debris, from a quantile model that beats a drag-physics baseline. Every forecast is scored after the fact."),
      link("#/scorecard", "Rocket Stage Scorecard", "Which launch vehicles leave exploding upper stages behind? Long March 6A against Falcon 9, from McDowell's GCAT."),
      link("#/sql", "SQL Lab", "DuckDB running in your browser over every derived table: breakup solutions, Δv, Gabbard points, forecasts."),
    ),
  );
  root.append(hero, boardSection, explore);
  boardSection.querySelector<HTMLAnchorElement>("a")?.blur();
  hero.querySelector<HTMLAnchorElement>('a[href="#board"]')?.addEventListener("click", (e) => {
    e.preventDefault();
    boardSection.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth" });
  });

  let disposeGlobe: (() => void) | null = null;
  let disposed = false;
  let events: EventIndexEntry[] = [];
  try {
    events = await api.events();
  } catch (e) {
    if (e instanceof DataMissing) {
      kpis.replaceChildren(h("p", { class: "secondary" }, "Kessler: coming online. The first data products are being computed."));
    } else board.replaceChildren(errorBox(e));
  }
  if (events.length) {
    const main = events.filter((e) => !e.stretch);
    const totalFrags = main.reduce((s, e) => s + e.n_fragments, 0);
    const solved = main.filter((e) => e.mode === "fragments").length;
    kpis.replaceChildren(
      kpi("Events tracked", String(main.length)),
      kpi("Fragments analysed", fmtNum(totalFrags)),
      kpi("Solved from fragments", `${solved} of ${main.length}`),
    );
    board.replaceChildren(...events.map(card));
  }

  // Globe is decorative here: load lazily, after content, and skip on tiny screens.
  import("../viz/globe").then(({ createGlobe }) => {
    if (disposed) return;
    const g = createGlobe(globeHost, { autoRotate: !prefersReducedMotion(), altitude: 2.2, interactive: false });
    disposeGlobe = () => g.dispose();
    if (events.length) loadBreakupMarkers(g.globe).catch(() => undefined);
  });

  return () => {
    disposed = true;
    disposeGlobe?.();
  };
}

async function loadBreakupMarkers(globe: import("globe.gl").GlobeInstance): Promise<void> {
  const evs = await api.events();
  const summaries = await Promise.all(evs.map((e) => api.event(e.id).catch(() => null)));
  const rings = summaries
    .filter((s): s is NonNullable<typeof s> => !!s && s.regime !== "GEO" && s.solution?.lat != null && s.solution?.lon != null)
    .map((s) => ({ lat: s.solution!.lat!, lng: s.solution!.lon!, alt: (s.solution!.alt_km ?? 500) / 6371, title: s.title }));
  globe
    .ringsData(rings)
    .ringLat("lat").ringLng("lng").ringAltitude("alt")
    .ringColor(() => (t: number) => `rgba(217,89,38,${1 - t})`)
    .ringMaxRadius(6).ringPropagationSpeed(2).ringRepeatPeriod(1600);
}

function link(href: string, title: string, body: string): HTMLElement {
  return h("a", { class: "ecard", href }, h("div", { class: "title" }, title, " →"), h("p", { class: "secondary small" }, body));
}

function kpi(k: string, v: string): HTMLElement {
  return h("div", {}, h("div", { class: "k" }, k), h("div", { class: "v" }, v));
}

function card(e: EventIndexEntry): HTMLElement {
  const v = e.validation;
  let badge: HTMLElement;
  if (!e.t_p50) badge = h("span", { class: "badge warning" }, h("span", { class: "dot" }), e.mode === "insufficient" ? "Awaiting data" : "No solution");
  else if (v && v.delta_min !== null) {
    const ok = v.within_precision;
    badge = h("span", { class: `badge ${ok ? "good" : "serious"}`, title: `Ours minus ${v.ref_label}` }, h("span", { class: "dot" }), `${fmtMinutes(v.delta_min)} vs reported`);
  } else badge = h("span", { class: "badge" }, h("span", { class: "dot" }), "Unvalidated");
  const ci = e.t_p05 && e.t_p95 && e.n_fragments > 1 ? `90% CI ${fmtMinutes((new Date(e.t_p05).getTime() - new Date(e.t_p50!).getTime()) / 60000)} / ${fmtMinutes((new Date(e.t_p95).getTime() - new Date(e.t_p50!).getTime()) / 60000)}` : "";
  return h(
    "a",
    { class: "ecard", href: `#/event/${e.id}` },
    h("div", { class: "row" }, h("span", { class: "eyebrow" }, `${e.regime} · NORAD ${e.parent_norad}`), h("span", { class: "spacer" }), badge),
    h("div", {}, h("div", { class: "title" }, e.title), h("div", { class: "when" }, e.t_p50 ? `t* ${fmtUTC(e.t_p50)}` : "breakup time not yet solvable", ci ? h("span", { class: "muted" }, ` · ${ci}`) : null)),
    sparkline(e),
    h(
      "div",
      { class: "facts" },
      h("div", {}, h("div", { class: "k" }, "Fragments"), h("div", { class: "v" }, fmtNum(e.n_fragments))),
      h("div", {}, h("div", { class: "k" }, "Reentered"), h("div", { class: "v" }, fmtNum(e.n_decayed))),
      h("div", {}, h("div", { class: "k" }, "Altitude"), h("div", { class: "v" }, e.alt_km != null ? `${fmtNum(e.alt_km)} km` : "—")),
    ),
    e.flags.length ? h("div", { class: "row" }, ...e.flags.slice(0, 3).map(flagBadge)) : null,
  );
}

/** Mini Gabbard diagram: period (x) vs apogee/perigee (y) for the latest snapshot. */
function sparkline(e: EventIndexEntry): SVGElement {
  const W = 320, H = 70, P = 4;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, role: "img", "aria-label": `Mini Gabbard diagram for ${e.title}` });
  const pts = e.sparkline;
  const bg = svgEl("rect", { x: 0, y: 0, width: W, height: H, rx: 8, fill: "rgba(255,255,255,0.02)" });
  svg.appendChild(bg);
  if (!pts.length) {
    const t = svgEl("text", { x: W / 2, y: H / 2 + 4, "text-anchor": "middle", fill: "var(--text-muted)", "font-size": 12 });
    t.textContent = "no fragment orbits yet";
    svg.appendChild(t);
    return svg;
  }
  const xs = pts.map((p) => p.period), ys = pts.flatMap((p) => [p.apo, p.peri]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const xr = Math.max(x1 - x0, 0.5), yr = Math.max(y1 - y0, 40);
  const xm = (x0 + x1) / 2, ym = (y0 + y1) / 2;
  const sx = (v: number) => W / 2 + ((v - xm) / xr) * (W - 4 * P) * 0.92;
  const sy = (v: number) => H / 2 - ((v - ym) / yr) * (H - 4 * P);
  for (const p of pts) {
    const color = p.parent ? "var(--series-1)" : "var(--series-2)";
    svg.appendChild(svgEl("circle", { cx: sx(p.period), cy: sy(p.apo), r: p.parent ? 4 : 2.6, fill: color, opacity: p.parent ? 1 : 0.9 }));
    svg.appendChild(svgEl("circle", { cx: sx(p.period), cy: sy(p.peri), r: p.parent ? 4 : 2.6, fill: "none", stroke: color, "stroke-width": 1.4, opacity: p.parent ? 1 : 0.8 }));
  }
  return svg;
}
