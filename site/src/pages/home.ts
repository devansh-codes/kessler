import { api, DataMissing } from "../api";
import type { Backtest, EventIndexEntry } from "../types";
import { errorBox, flagBadge, fmtDate, fmtMinutes, fmtNum, h, prefersReducedMotion } from "../ui";
import { cardArt, dottedMap, reticle, stepArt } from "../viz/porthole";

export async function render(root: HTMLElement): Promise<() => void> {
  let disposed = false;
  let disposeGlobe: (() => void) | null = null;

  // ------------------------------------------------------------------ hero
  const globeHost = h("div", { class: "globe-host", "aria-hidden": "true" });
  const port = h("div", { class: "porthole" }, globeHost);
  port.appendChild(reticle({ inner: 372 }));
  const kpis = h("div", { class: "kpis" });
  const hero = h(
    "section",
    { class: "hero" },
    h(
      "div",
      { class: "wrap hero-inner" },
      port,
      h(
        "div",
        { class: "hero-copy" },
        h(
          "div",
          { class: "stack-lg" },
          h("p", { class: "eyebrow" }, "Orbital breakup forensics · 2026"),
          h("h1", {}, "2026's orbital breakups, ", h("em", {}, "reconstructed from public data")),
          h("p", { class: "lede" }, "When a satellite or rocket stage comes apart, the pieces keep a record. Kessler reads it back: when and where the object fragmented, how hard each piece was kicked, and when the debris will fall. It uses public CelesTrak element sets only."),
          h("div", { class: "row", style: "gap:14px" }, h("a", { class: "btn primary lg", href: "#board" }, "Explore the breakups"), h("a", { class: "btn lg", href: "#/methods" }, "How it works")),
          kpis,
        ),
      ),
    ),
  );

  // ------------------------------------------------------------------ map band
  const mapCanvas = h("canvas", { role: "img", "aria-label": "World map with solved breakup locations" }) as HTMLCanvasElement;
  const icon = (d: string) => {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("width", "24"); s.setAttribute("height", "24");
    s.innerHTML = d;
    return h("div", { class: "icon" }, s);
  };
  const mapBand = h(
    "section",
    { class: "band band-pad" },
    h(
      "div",
      { class: "wrap" },
      h("h2", { class: "center" }, "Six breakups. ", h("em", {}, "One public catalog.")),
      h("div", { class: "legend-inline" }, h("span", {}, h("i", { style: "background:var(--gold)" }), "Breakup location solved"), h("span", {}, h("i", { style: "background:#5b6c88" }), "Land")),
      h(
        "div",
        { class: "grid", style: "grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:48px;margin-top:40px;align-items:center" },
        h("div", { class: "map-wrap" }, mapCanvas),
        h(
          "div",
          { class: "features" },
          h("div", { class: "feature" }, icon('<circle cx="12" cy="12" r="4" fill="none" stroke="#e2b979" stroke-width="1.5"/><ellipse cx="12" cy="12" rx="10" ry="4" fill="none" stroke="#1f8a96" stroke-width="1.5" transform="rotate(-25 12 12)"/>'), h("div", {}, h("h3", {}, "Real catalog data"), h("p", {}, "Every element set comes from CelesTrak's public GP feed, in OMM format, so six-digit NORAD numbers like 100472 just work."))),
          h("div", { class: "feature" }, icon('<circle cx="12" cy="12" r="9" fill="none" stroke="#e2b979" stroke-width="1.5"/><path d="M12 7v5l3 2" fill="none" stroke="#1f8a96" stroke-width="1.5"/>'), h("div", {}, h("h3", {}, "Forensics, not guesses"), h("p", {}, "Two independent estimators, bootstrap intervals and honest flags. Where the data is thin, the page says so."))),
          h("div", { class: "feature" }, icon('<path d="M4 12a8 8 0 1 1 3 6.2" fill="none" stroke="#e2b979" stroke-width="1.5"/><path d="M4 18v-5h5" fill="none" stroke="#1f8a96" stroke-width="1.5"/>'), h("div", {}, h("h3", {}, "Updated every six hours"), h("p", {}, "A polite pipeline on GitHub Actions re-ingests, re-solves and re-forecasts. Every request is logged on the Status page."))),
        ),
      ),
    ),
  );

  // ------------------------------------------------------------------ data sources
  const wm = (name: string, sub: string, href: string) => h("a", { class: "wordmark", href, rel: "noopener" }, h("b", {}, name), h("small", {}, sub));
  const sources = h(
    "section",
    { class: "band-black", style: "padding:64px 0" },
    h(
      "div",
      { class: "wrap" },
      h("p", { class: "eyebrow center", style: "margin-bottom:34px;color:var(--text-muted)" }, "Built entirely on open data and open tools"),
      h(
        "div",
        { class: "wordmarks" },
        wm("CelesTrak", "Orbital elements · SATCAT", "https://celestrak.org"),
        wm("18 SDS", "Space surveillance source", "https://celestrak.org/NORAD/elements/"),
        wm("GCAT", "J. McDowell · CC-BY 4.0", "https://planet4589.org/space/gcat"),
        wm("NOAA SWPC", "Live space weather", "https://www.swpc.noaa.gov/"),
        wm("NASA", "Visible Earth imagery", "https://visibleearth.nasa.gov/"),
        wm("SGP4", "Vallado / python-sgp4", "https://pypi.org/project/sgp4/"),
        wm("DuckDB", "Warehouse + WASM SQL", "https://duckdb.org"),
      ),
    ),
  );

  // ------------------------------------------------------------------ board
  const board = h("div", { class: "board" });
  const boardBand = h(
    "section",
    { class: "band band-pad", id: "board" },
    h(
      "div",
      { class: "wrap" },
      h("h2", { class: "center" }, "Reconstructed ", h("em", {}, "breakups")),
      h("p", { class: "subtitle-serif center", style: "margin:10px 0 44px" }, "Each card is a telescope view of the event's latest Gabbard snapshot"),
      board,
    ),
  );

  // ------------------------------------------------------------------ steps
  const step = (n: number, kind: "collect" | "rewind" | "measure", title: string, body: string) =>
    h("div", { class: "step" }, h("div", { class: "art" }, stepArt(kind)), h("div", { class: "body" }, h("span", { class: "step-tag" }, `Step ${n}`), h("h3", {}, title), h("p", {}, body)));
  const steps = h(
    "section",
    { class: "band-2 band-pad" },
    h(
      "div",
      { class: "wrap" },
      h("h2", { class: "center" }, "From catalog to ", h("em", {}, "forensics")),
      h("p", { class: "subtitle-serif center", style: "margin:10px 0 44px" }, "3 simple steps, repeated every six hours"),
      h(
        "div",
        { class: "steps" },
        step(1, "collect", "Gather the evidence", "Pull every element set that shares the parent's designator, including the first catalogued sets of debris that has already fallen."),
        step(2, "rewind", "Rewind the clock", "Back-propagate the cloud and find the instant when every fragment's orbit passes through the parent's position."),
        step(3, "measure", "Measure and forecast", "Recover each fragment's velocity kick, then forecast its reentry with a calibrated quantile model."),
      ),
    ),
  );

  // ------------------------------------------------------------------ explore pills
  const explore = h(
    "section",
    { class: "band band-pad" },
    h(
      "div",
      { class: "wrap center" },
      h("h2", {}, "Explore ", h("em", {}, "the lab")),
      h(
        "div",
        { class: "pills", style: "margin-top:36px" },
        ...[["#board", "Breakup Board"], ["#/reentry", "Reentry Watch"], ["#/scorecard", "Rocket Scorecard"], ["#/sql", "SQL Lab"], ["#/methods", "Methods"], ["#/status", "Pipeline Status"]].map(([href, label]) => h("a", { class: "btn primary", href }, label)),
      ),
    ),
  );

  // ------------------------------------------------------------------ model "plans"
  const plans = h("div", { class: "plans" });
  const plansBand = h(
    "section",
    { class: "band-2 band-pad" },
    h(
      "div",
      { class: "wrap" },
      h("h2", { class: "center" }, "Pick your ", h("em", {}, "forecaster")),
      h("p", { class: "lede center", style: "margin:14px auto 44px" }, "Three ways to predict when debris will fall, scored on the same time-ordered holdout of reentered objects. Lower error is better; 80% intervals should contain the truth 80% of the time."),
      plans,
    ),
  );

  root.append(hero, mapBand, sources, boardBand, steps, explore, plansBand);
  hero.querySelector<HTMLAnchorElement>('a[href="#board"]')?.addEventListener("click", (e) => {
    e.preventDefault();
    boardBand.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth" });
  });
  explore.querySelector<HTMLAnchorElement>('a[href="#board"]')?.addEventListener("click", (e) => {
    e.preventDefault();
    boardBand.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth" });
  });

  // ------------------------------------------------------------------ data
  let events: EventIndexEntry[] = [];
  try {
    events = await api.events();
  } catch (e) {
    if (e instanceof DataMissing) kpis.replaceChildren(h("p", { class: "secondary" }, "Kessler: coming online. The first data products are being computed."));
    else board.replaceChildren(errorBox(e));
  }
  if (events.length) {
    const main = events.filter((e) => !e.stretch);
    kpis.replaceChildren(
      kpi("Events tracked", String(main.length)),
      kpi("Fragments analysed", fmtNum(main.reduce((s, e) => s + e.n_fragments, 0))),
      kpi("Solved from fragments", `${main.filter((e) => e.mode === "fragments").length} of ${main.length}`),
    );
    board.replaceChildren(...events.map(ocard));
    Promise.all(events.map((e) => api.event(e.id).catch(() => null))).then((sums) => {
      const marks = sums.filter((s): s is NonNullable<typeof s> => !!s && s.solution?.lat != null).map((s) => ({ lat: s.solution!.lat!, lon: s.solution!.lon!, label: s.title.replace(/ (breakup|fragmentation|GEO event)$/i, ""), solved: true }));
      if (!disposed) dottedMap(mapCanvas, marks).catch(() => undefined);
    });
  }
  api.backtest().then((bt) => plans.replaceChildren(...planCards(bt))).catch(() => plansBand.remove());

  import("../viz/globe").then(({ createGlobe }) => {
    if (disposed) return;
    const g = createGlobe(globeHost, { autoRotate: !prefersReducedMotion(), altitude: 2.05, interactive: false });
    disposeGlobe = () => g.dispose();
  });

  return () => {
    disposed = true;
    disposeGlobe?.();
  };
}

function kpi(k: string, v: string): HTMLElement {
  return h("div", {}, h("div", { class: "k" }, k), h("div", { class: "v" }, v));
}

function ocard(e: EventIndexEntry): HTMLElement {
  const v = e.validation;
  let badge: HTMLElement;
  if (!e.t_p50) badge = h("span", { class: "badge warning corner-badge" }, h("span", { class: "dot" }), e.mode === "insufficient" ? "Awaiting data" : "Parent-only");
  else if (v && v.delta_min !== null) badge = h("span", { class: `badge ${v.within_precision ? "good" : "serious"} corner-badge` }, h("span", { class: "dot" }), `${fmtMinutes(v.delta_min)} vs reported`);
  else badge = h("span", { class: "badge corner-badge" }, h("span", { class: "dot" }), "Unvalidated");
  const when = e.t_p50 ?? v?.ref_time ?? null;
  const view = h("div", { class: "view" }, badge);
  view.appendChild(cardArt(e));
  const flags = e.flags.filter((f) => !["PARENT_ONLY", "NO_PUBLIC_FRAGMENTS"].includes(f)).slice(0, 1);
  return h(
    "a",
    { class: "ocard", href: `#/event/${e.id}` },
    view,
    h(
      "div",
      { class: "cap" },
      h("div", { class: "meta" }, `${fmtDate(when)} · ${e.regime} · NORAD ${e.parent_norad}`),
      h("div", { class: "title" }, e.title),
      h(
        "div",
        { class: "facts" },
        h("div", {}, h("div", { class: "k" }, "Fragments"), h("div", { class: "v" }, fmtNum(e.n_fragments))),
        h("div", {}, h("div", { class: "k" }, "Reentered"), h("div", { class: "v" }, fmtNum(e.n_decayed))),
        h("div", {}, h("div", { class: "k" }, "Altitude"), h("div", { class: "v" }, e.alt_km != null ? `${fmtNum(e.alt_km)} km` : "—")),
        h("div", {}, h("div", { class: "k" }, "Mode"), h("div", { class: "v" }, e.mode === "fragments" ? "Solved" : e.mode === "parent_only" ? "Parent" : "Pending")),
      ),
      flags.length ? h("div", { style: "margin-top:10px" }, ...flags.map((f) => { const b = flagBadge(f); b.style.background = "#f1efe9"; b.style.color = "#3a3f49"; b.style.borderColor = "#e3e1db"; return b; })) : null,
    ),
  );
}

function planCards(bt: Backtest): HTMLElement[] {
  const get = (prefix: string) => bt.metrics.find((m) => m.model.startsWith(prefix));
  const items = [
    { m: get("Physics baseline"), name: "Baseline", tag: "Drag physics: time for the decay rate to reach 180 km", featured: false, extra: "No training data needed" },
    { m: get("Quantile GBM (raw)"), name: "Quantile", tag: "Gradient-boosted quantiles on log-days", featured: false, extra: "Seven quantile models" },
    { m: get("Quantile GBM +"), name: "Conformal", tag: "Quantiles recalibrated with split-conformal prediction", featured: true, extra: "Kessler's live forecaster" },
  ];
  return items.filter((i) => i.m).map((i) =>
    h(
      "div",
      { class: `plan${i.featured ? " featured" : ""}` },
      h("h3", {}, i.name),
      h("p", { class: "tag" }, i.tag),
      h("div", { class: "price" }, `${fmtNum(i.m!.mae_days, 1)}`, h("small", {}, "days MAE")),
      h("p", { class: "save" }, i.m!.skill_vs_baseline ? `${fmtNum(i.m!.skill_vs_baseline * 100, 0)}% lower error than baseline` : " "),
      h("a", { class: `btn ${i.featured ? "primary" : ""}`, href: "#/reentry", style: "margin-top:6px" }, i.featured ? "See live forecasts" : "See the backtest"),
      h(
        "ul",
        {},
        h("li", {}, `80% interval coverage: ${fmtNum(i.m!.coverage80 * 100, 0)}%`),
        h("li", {}, `Mean error ${fmtNum(i.m!.mae_pct, 0)}% of remaining lifetime`),
        h("li", {}, i.m!.median_lead_days != null ? `Stays calibrated ${fmtNum(i.m!.median_lead_days, 0)} days out (median)` : "Lead time not measured"),
        h("li", {}, `Holdout: ${fmtNum(bt.n_holdout)} element sets`),
        h("li", {}, i.extra),
      ),
    ),
  );
}
