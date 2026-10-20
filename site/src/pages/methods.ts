import { api } from "../api";
import { h } from "../ui";

export async function render(root: HTMLElement): Promise<void> {
  const m = await api.manifest().catch(() => null);
  const release = m?.gcat_release ?? "1.8.8";
  const P = (...c: (string | Node)[]) => h("p", {}, ...c);
  const F = (s: string) => h("div", { class: "formula" }, s);
  const LI = (...c: (string | Node)[]) => h("li", {}, ...c);
  root.append(
    h(
      "div",
      { class: "wrap" },
      h(
        "article",
        { class: "prose", style: "padding:32px 0 64px" },
        h("p", { class: "eyebrow" }, "Methods"),
        h("h1", {}, "How Kessler works"),
        P(
          "Kessler is a static site rebuilt from a Parquet warehouse every six hours. Python pipelines on GitHub Actions fetch public data, DuckDB runs the analysis, and the browser renders precomputed products. There is no server, no database process and no API key.",
        ),

        h("h2", {}, "1. Data"),
        h(
          "ul",
          {},
          LI(h("strong", {}, "Orbital elements: "), "CelesTrak GP data in OMM format (CSV). The legacy TLE format cannot represent catalog numbers above 99,999, and the catalog crossed 100,000 on 11 July 2026, so Kessler never requests TLEs. We use the current, first-catalogued (", h("code", {}, "gp-first.php"), ") and last-before-decay (", h("code", {}, "gp-last.php"), ") element sets."),
          LI(h("strong", {}, "Catalog: "), "CelesTrak SATCAT supplies object types, owners and decay dates. Decay dates are day-precision, so every reentry label carries about ±12 hours of noise."),
          LI(h("strong", {}, "Space weather: "), "CelesTrak SpaceData (F10.7, Ap, Kp since 1957) and NOAA SWPC live Kp."),
          LI(h("strong", {}, "Launch lineage: "), "GCAT by Jonathan McDowell, which links every debris object to its parent stage and launch."),
        ),
        P(
          "Ingest is deliberately polite. CelesTrak firewalls clients that make about 50 failed requests in two hours. Every response is cached for two hours, the first non-200 response stops all further CelesTrak requests in that run, nothing is ever retried, and a persistent error ledger refuses to make requests once five errors have occurred. The Status page shows every request.",
        ),

        h("h2", {}, "2. Which objects belong to an event"),
        P("Candidates are debris objects sharing the parent's international designator. Each one must pass two tests:"),
        h(
          "ul",
          {},
          LI(h("strong", {}, "Time: "), "it was first catalogued no earlier than one day before the reported event."),
          LI(h("strong", {}, "Orbital plane: "), "DBSCAN on the angle between orbit planes, measured at the epoch when the new debris was catalogued. Fresh debris shares the parent's plane. Old debris has been rotated away by differential J2 precession over the years. This is what separates Meteor 2-7's 2004 cloud from anything new."),
        ),

        h("h2", {}, "3. When and where it broke up"),
        P("Two estimators run on the parent's element set and each fragment's earliest element set:"),
        h(
          "ul",
          {},
          LI(h("strong", {}, "SGP4 spread "), "(the textbook method): back-propagate everything with SGP4 and find the time that minimises the median parent–fragment distance."),
          LI(h("strong", {}, "Orbit crossing: "), "at the breakup instant the parent's position lies on every fragment's orbit. We minimise the median distance from the parent to each fragment's osculating ellipse. Along-track error does not affect this, so it pins down the argument of latitude of the breakup to within a few kilometres. It cannot by itself tell which revolution the breakup happened on."),
        ),
        P(
          "The published ", h("strong", {}, "hybrid"), " solution lets the SGP4 spread choose the revolution and the orbit crossing fix the time within it. 500 bootstrap resamples over fragments give the 90% interval, refined to about one second. A second solve using each fragment's second element set checks sensitivity. Location comes from the parent's state at t*, rotated TEME → Earth-fixed (GMST) → WGS-84 geodetic.",
        ),
        F("objective(t) = median_i ‖ r_i(t) − r_parent(t) ‖        (SGP4 spread)\ncrossing(t)  = median_i dist( r_parent(t), ellipse_i(t) )   (orbit crossing)"),
        P(
          "Flags are honest about weakness. ", h("code", {}, "LOW_CONFIDENCE"), " means the cloud's SGP4 spread at t* exceeds 200 km. ", h("code", {}, "LONG_BACKPROP"), " means fragments were first catalogued more than a week after t*; SGP4 back-propagation error grows by roughly kilometres per day, and much faster for high-drag fragments. ", h("code", {}, "MULTIMODAL"), " means bootstrap resamples disagree about the revolution.",
        ),

        h("h2", {}, "4. Velocity kicks"),
        P(
          "For each fragment we search its own orbit (±half a period around t*) for the point closest to the breakup location, and take Δv = v_fragment − v_parent there. We then express it in the parent's radial / transverse / normal frame. Measuring at the closest point rather than at t* makes the result robust to along-track timing error. Fragments whose orbit misses the point by more than 500 km are marked unreliable. The |Δv| distribution is summarised by its median, 90th percentile and a log-normal fit.",
        ),
        F("R = r̂,  N = (r × v)/|r × v|,  T = N × R"),
        P(
          "A permanent regression test plants a synthetic breakup in a real orbit: 25 fragments with 20 m/s kicks, catalogued two days later with 5 km of along-track noise. The solver must recover the time to within 2 minutes and the median |Δv| to within 20%.",
        ),

        h("h2", {}, "5. When no fragments are public"),
        P(
          "Parent-only mode looks for the event in the parent's own history. It runs changepoint detection (PELT) on mean motion, eccentricity and B*, and estimates the along-track kick from the change in semi-major axis, Δv_t ≈ (n·a/2)(Δa/a). Our archive started on 20 October 2026, so events earlier than that need element sets bracketing the event, which may not be public. The page says so when that is the case.",
        ),

        h("h2", {}, "6. Reentry forecasts"),
        P(
          "Training rows are archived element sets of objects that later reentered, labelled with days until the SATCAT decay date (up to 120 days). Features: perigee and apogee altitude, mean motion and its derivative, B*, radar cross-section, object type, the 81-day F10.7 mean, Ap, the 3-day maximum Kp and the physics baseline.",
        ),
        F("baseline: t ≈ (n_crit − n) / (2 · MEAN_MOTION_DOT),   n_crit ≈ 16.35 rev/day (180 km)"),
        P(
          "Seven gradient-boosted quantile regressors predict log(days). Split-conformal prediction (CQR) widens each central interval on a calibration block. The backtest is strictly time-ordered: oldest 60% for training, next 20% for calibration, newest 20% held out. Training rows must belong to objects that had already reentered before the block they are tested on, otherwise the label would leak from the future. Every live forecast is stored with its issue time and scored automatically once the object reenters.",
        ),

        h("h2", {}, "7. Caveats"),
        h(
          "ul",
          {},
          LI("SGP4 is a mean-element theory with kilometre-level errors that grow with propagation time. Breakup times solved from fragments catalogued weeks later are indicative, and the flags say so."),
          LI("The public catalog lags reality. Debris can take days to months to appear, and some never does."),
          LI("Decay dates are day-precision labels."),
          LI("The rocket scorecard counts catalogued pieces only. Small debris is invisible to it."),
          LI("Raw element sets are not redistributed on this site, only derived products."),
        ),

        h("h2", {}, "Attribution"),
        h(
          "ul",
          {},
          LI("Orbital data: ", h("a", { href: "https://celestrak.org" }, "CelesTrak"), " (Dr. T.S. Kelso), sourced from 18 SDS / Space-Track."),
          LI("Launch lineage: McDowell, Jonathan C., 2020. General Catalog of Artificial Space Objects, Release ", release, ", ", h("a", { href: "https://planet4589.org/space/gcat" }, "https://planet4589.org/space/gcat"), ". Licensed CC-BY 4.0."),
          LI("Space weather: ", h("a", { href: "https://celestrak.org/SpaceData/" }, "CelesTrak SpaceData"), " and ", h("a", { href: "https://www.swpc.noaa.gov/" }, "NOAA SWPC"), " (public domain)."),
          LI("Earth imagery: NASA Visible Earth Blue Marble (public domain)."),
          LI("Event references: US Space Forces-Space, LeoLabs, KeepTrack, Jim Shell, s2a systems, SpaceX, as cited on each event page."),
          LI("Libraries: python-sgp4 (Brandon Rhodes), DuckDB, scikit-learn, ruptures, globe.gl / three.js, Observable Plot."),
        ),
        P("Code is MIT-licensed: ", h("a", { href: "https://github.com/devansh-codes/kessler" }, "github.com/devansh-codes/kessler"), "."),
      ),
    ),
  );
}
