// Animated debris cloud on the globe: play/pause/scrub over precomputed ephemerides.
import { api, interpState } from "../api";
import type { EphemMeta } from "../types";
import { fmtUTC, h, prefersReducedMotion } from "../ui";
import { createGlobe, DebrisLayer } from "./globe";

const PARENT = "#3987e5";
const FRAG = "#d95926";
const SAMPLES_PER_SECOND = 14;

/** ``stress`` > 0 replicates the fragments (with longitude offsets) to benchmark ~N objects. */
export async function mountDebrisPlayer(shell: HTMLElement, eventId: string, meta0: EphemMeta, stress = 0): Promise<() => void> {
  let meta = meta0;
  const host = h("div", { class: "globe-host" });
  const clock = h("div", { class: "clock", "aria-live": "off" }, "—");
  const phase = h("div", { class: "badge", style: "pointer-events:none" }, "");
  const count = h("div", { class: "small secondary", style: "background:rgba(10,12,16,.72);padding:4px 8px;border-radius:6px" }, "");
  const hud = h("div", { class: "globe-hud" }, clock, phase, count);
  const nFrag = meta.N - 1;
  const legend = h(
    "div",
    { class: "globe-legend" },
    h("span", { class: "key" }, h("i", { style: `background:${PARENT}` }), "Parent"),
    nFrag > 0 ? h("span", { class: "key" }, h("i", { style: `background:${FRAG}` }), `Fragments (${nFrag})`) : null,
    meta.breakup ? h("span", { class: "key" }, h("i", { class: "ring", style: `color:${FRAG}` }), "Breakup point") : null,
  );
  const play = h("button", { class: "btn", type: "button", "aria-label": "Play" }, "▶ Play");
  const slider = h("input", { type: "range", min: "0", max: String(meta.T - 1), step: "0.01", value: "0", "aria-label": "Timeline" }) as HTMLInputElement;
  const speed = h("button", { class: "btn", type: "button", title: "Playback speed" }, "1×");
  const timeline = h("div", { class: "timeline" }, play, slider, speed);
  shell.append(host, hud, legend, timeline);

  let data = await api.ephem(eventId, meta);
  if (stress > meta.N) [data, meta] = replicate(data, meta, stress);
  const g = createGlobe(host, { autoRotate: false, altitude: 1.9 });
  const globe = g.globe;
  if (meta.breakup) {
    globe.pointOfView({ lat: meta.breakup.lat, lng: meta.breakup.lon, altitude: 1.9 }, 0);
    const alt = meta.breakup.alt_km / 6371;
    globe
      .ringsData([{ lat: meta.breakup.lat, lng: meta.breakup.lon, alt }])
      .ringLat("lat").ringLng("lng").ringAltitude("alt")
      .ringColor(() => (t: number) => `rgba(217,89,38,${0.9 * (1 - t)})`)
      .ringMaxRadius(5).ringPropagationSpeed(1.6).ringRepeatPeriod(1400);
  }

  const parentIdx = meta.parent_index;
  const fragIdx = meta.norads.map((_, i) => i).filter((i) => i !== parentIdx);
  const parentLayer = new DebrisLayer(globe, 1, [PARENT], 6, 14);
  const fragLayer = fragIdx.length ? new DebrisLayer(globe, fragIdx.length, fragIdx.map(() => FRAG), 4.2, 10) : null;
  const times = meta.times;
  const dense = meta.dense_until_s ?? 43200;
  const denseCount = times.filter((t) => t <= dense).length;
  const t0 = new Date(meta.t0).getTime();

  let pos = 0; // fractional sample index
  let playing = false;
  let speedMul = 1;
  let raf = 0;
  let lastTs = 0;

  const fadeArr = new Float32Array(fragIdx.length);
  const tSecAt = (p: number): number => {
    const i = Math.floor(p), f = p - i;
    if (i >= times.length - 1) return times[times.length - 1];
    return times[i] + (times[i + 1] - times[i]) * f;
  };

  function trailFor(obj: number, p: number, K: number): ([number, number, number] | null)[] {
    const out: ([number, number, number] | null)[] = [];
    if (p >= denseCount - 1) return out;
    for (let k = K - 1; k >= 0; k--) {
      const q = p - k * 0.5;
      out.push(q < 0 ? null : interpState(data, times, meta.N, obj, tSecAt(q)));
    }
    return out;
  }

  const perf = { frames: 0, drawMs: 0, start: performance.now() };
  (window as unknown as { __kessler?: unknown }).__kessler = { perf, N: meta.N };
  function draw(): void {
    const d0 = performance.now();
    drawInner();
    perf.drawMs += performance.now() - d0;
    perf.frames++;
  }
  function drawInner(): void {
    const tSec = tSecAt(pos);
    const ps = interpState(data, times, meta.N, parentIdx, tSec);
    parentLayer.update([ps], undefined, [trailFor(parentIdx, pos, 14)]);
    let visible = 0;
    if (fragLayer) {
      const states = fragIdx.map((obj, j) => {
        const d = meta.decay_s[obj];
        fadeArr[j] = d === null || d === undefined ? 1 : Math.max(0, Math.min(1, (d - tSec) / 86400));
        const s = interpState(data, times, meta.N, obj, tSec);
        if (s && fadeArr[j] > 0) visible++;
        return s;
      });
      fragLayer.update(states, fadeArr, fragIdx.map((obj) => trailFor(obj, pos, 10)));
    }
    clock.textContent = fmtUTC(new Date(t0 + tSec * 1000).toISOString());
    const hrs = tSec / 3600;
    phase.textContent = tSec <= dense
      ? `T+${hrs.toFixed(1)} h · ${meta.reconstructed ? "reconstructed from fitted Δv" : "SGP4"}`
      : `T+${(tSec / 86400).toFixed(0)} d · SGP4 daily snapshot`;
    count.textContent = nFrag > 0 ? `${visible} of ${nFrag} fragments in orbit` : "No public fragments: parent only";
    slider.value = String(pos);
    slider.setAttribute("aria-valuetext", clock.textContent ?? "");
  }

  function frame(ts: number): void {
    if (!playing) return;
    const dt = lastTs ? (ts - lastTs) / 1000 : 0;
    lastTs = ts;
    pos += dt * SAMPLES_PER_SECOND * speedMul * (pos < denseCount ? 1 : 0.35);
    if (pos >= meta.T - 1) {
      pos = meta.T - 1;
      setPlaying(false);
    }
    draw();
    raf = requestAnimationFrame(frame);
  }

  function setPlaying(p: boolean): void {
    playing = p;
    play.textContent = p ? "❚❚ Pause" : "▶ Play";
    play.setAttribute("aria-label", p ? "Pause" : "Play");
    if (p) {
      if (pos >= meta.T - 1) pos = 0;
      lastTs = 0;
      raf = requestAnimationFrame(frame);
    } else cancelAnimationFrame(raf);
  }

  play.addEventListener("click", () => setPlaying(!playing));
  slider.addEventListener("input", () => {
    pos = Number(slider.value);
    draw();
  });
  const speeds = [1, 2, 4, 0.5];
  speed.addEventListener("click", () => {
    speedMul = speeds[(speeds.indexOf(speedMul) + 1) % speeds.length];
    speed.textContent = `${speedMul}×`;
  });
  const onKey = (e: KeyboardEvent) => {
    const tgt = e.target as HTMLElement;
    if (tgt && (tgt.tagName === "INPUT" && tgt !== slider || tgt.tagName === "TEXTAREA")) return;
    if (e.key === " " && shell.contains(document.activeElement)) {
      e.preventDefault();
      setPlaying(!playing);
    }
  };
  shell.addEventListener("keydown", onKey);
  draw();
  if (!prefersReducedMotion()) setPlaying(true);

  return () => {
    setPlaying(false);
    shell.removeEventListener("keydown", onKey);
    parentLayer.dispose();
    fragLayer?.dispose();
    g.dispose();
  };
}

function replicate(data: Float32Array, meta: EphemMeta, n: number): [Float32Array, EphemMeta] {
  const frags = meta.norads.map((_, i) => i).filter((i) => i !== meta.parent_index);
  if (!frags.length) return [data, meta];
  const N = n;
  const out = new Float32Array(meta.T * N * 3);
  const src: number[] = [meta.parent_index];
  for (let k = 1; k < N; k++) src.push(frags[k % frags.length]);
  for (let t = 0; t < meta.T; t++) {
    for (let j = 0; j < N; j++) {
      const s = (t * meta.N + src[j]) * 3, d = (t * N + j) * 3;
      out[d] = data[s];
      let lon = data[s + 1] + (j === 0 ? 0 : ((j * 37) % 360) * 0.05);
      if (lon > 180) lon -= 360;
      out[d + 1] = lon;
      out[d + 2] = data[s + 2];
    }
  }
  return [out, { ...meta, N, parent_index: 0, norads: src.map((i) => meta.norads[i]), names: src.map((i) => meta.names[i]), decay_s: src.map((i) => meta.decay_s[i]) }];
}
