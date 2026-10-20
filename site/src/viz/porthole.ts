// Telescope-reticle "porthole" frames, card artwork, dotted world map and step illustrations.
import { BASE } from "../api";
import type { EventIndexEntry } from "../types";

const NS = "http://www.w3.org/2000/svg";
const GOLD = "#e2b979";
const GOLD_LINE = "#65563e";
const TEAL = "#0e5966";
const TEAL_B = "#1f8a96";

function el(tag: string, attrs: Record<string, string | number>, parent?: Element): SVGElement {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  parent?.appendChild(e);
  return e;
}

/** Reticle overlay in a 1000×1000 viewBox. ``inner`` is the radius of the clear aperture. */
export function reticle(opts: { inner?: number; labels?: boolean; brackets?: boolean; crosshair?: boolean } = {}): SVGSVGElement {
  const inner = opts.inner ?? 410;
  const svg = el("svg", { viewBox: "0 0 1000 1000", class: "reticle", "aria-hidden": "true" }) as SVGSVGElement;
  const c = 500;
  // corner brackets
  if (opts.brackets !== false) {
    const L = 120, m = 18;
    for (const [x, y, dx, dy] of [[m, m, 1, 1], [1000 - m, m, -1, 1], [m, 1000 - m, 1, -1], [1000 - m, 1000 - m, -1, -1]]) {
      el("path", { d: `M${x} ${y + dy * L} V${y} H${x + dx * L}`, fill: "none", stroke: GOLD_LINE, "stroke-width": 2 }, svg);
      el("path", { d: `M${x + dx * 14} ${y + dy * 34} V${y + dy * 14} H${x + dx * 34}`, fill: "none", stroke: TEAL_B, "stroke-width": 2 }, svg);
    }
  }
  // rings
  el("circle", { cx: c, cy: c, r: inner + 78, fill: "none", stroke: GOLD_LINE, "stroke-width": 2 }, svg);
  el("circle", { cx: c, cy: c, r: inner + 52, fill: "none", stroke: TEAL, "stroke-width": 34, opacity: 0.55 }, svg);
  el("circle", { cx: c, cy: c, r: inner + 69, fill: "none", stroke: TEAL_B, "stroke-width": 1.5, opacity: 0.7 }, svg);
  el("circle", { cx: c, cy: c, r: inner + 34, fill: "none", stroke: TEAL_B, "stroke-width": 1.5, opacity: 0.7 }, svg);
  el("circle", { cx: c, cy: c, r: inner + 10, fill: "none", stroke: GOLD_LINE, "stroke-width": 1.5 }, svg);
  // ticks + labels
  for (let d = 0; d < 360; d += 5) {
    const a = ((d - 90) * Math.PI) / 180;
    const major = d % 30 === 0;
    const r1 = inner + 36, r2 = inner + (major ? 66 : 46);
    el("line", { x1: c + r1 * Math.cos(a), y1: c + r1 * Math.sin(a), x2: c + r2 * Math.cos(a), y2: c + r2 * Math.sin(a), stroke: major ? GOLD : TEAL_B, "stroke-width": major ? 2 : 1, opacity: major ? 0.75 : 0.5 }, svg);
    if (major && opts.labels !== false) {
      const rl = inner + 92;
      const t = el("text", { x: c + rl * Math.cos(a), y: c + rl * Math.sin(a) + 6, "text-anchor": "middle", fill: GOLD, "font-size": 17, "font-family": "Jost, sans-serif", "font-weight": 500, opacity: 0.8 }, svg);
      t.textContent = String(d);
    }
  }
  // triangle markers
  for (let d = 15; d < 360; d += 45) {
    const a = ((d - 90) * Math.PI) / 180;
    const r = inner + 20;
    const x = c + r * Math.cos(a), y = c + r * Math.sin(a);
    const rot = d;
    el("path", { d: "M0 -9 L8 6 L-8 6 Z", transform: `translate(${x} ${y}) rotate(${rot})`, fill: "none", stroke: TEAL_B, "stroke-width": 1.5, opacity: 0.8 }, svg);
  }
  if (opts.crosshair !== false) {
    el("line", { x1: c - inner, y1: c, x2: c + inner, y2: c, stroke: GOLD, "stroke-width": 1, opacity: 0.22 }, svg);
    el("line", { x1: c, y1: c - inner, x2: c, y2: c + inner, stroke: GOLD, "stroke-width": 1, opacity: 0.22 }, svg);
    el("circle", { cx: c, cy: c, r: 26, fill: "none", stroke: GOLD, "stroke-width": 1.5, opacity: 0.55 }, svg);
    el("circle", { cx: c, cy: c, r: 15, fill: "none", stroke: TEAL_B, "stroke-width": 1.5, opacity: 0.8 }, svg);
  }
  return svg;
}

function rng(seed: number): () => number {
  let s = seed >>> 0 || 1;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** Card artwork: a porthole view of the event's latest Gabbard snapshot over a seeded starfield. */
export function cardArt(e: EventIndexEntry): SVGSVGElement {
  const svg = el("svg", { viewBox: "0 0 1000 950", role: "img", "aria-label": `Telescope view of ${e.title}: Gabbard snapshot of ${e.n_fragments} fragments` }) as SVGSVGElement;
  const c = 500, cy = 475, R = 380;
  const id = `clip-${e.id}`;
  const defs = el("defs", {}, svg);
  const clip = el("clipPath", { id }, defs);
  el("circle", { cx: c, cy, r: R }, clip);
  const glow = el("radialGradient", { id: `g-${e.id}` }, defs);
  el("stop", { offset: "0%", "stop-color": e.n_fragments ? "#2a1408" : "#0a1726", "stop-opacity": 0.95 }, glow);
  el("stop", { offset: "100%", "stop-color": "#000", "stop-opacity": 1 }, glow);
  el("circle", { cx: c, cy, r: R, fill: `url(#g-${e.id})` }, svg);
  const g = el("g", { "clip-path": `url(#${id})` }, svg);
  const rand = rng(hash(e.id));
  for (let i = 0; i < 160; i++) {
    const a = rand() * Math.PI * 2, r = Math.sqrt(rand()) * R;
    el("circle", { cx: c + r * Math.cos(a), cy: cy + r * Math.sin(a), r: rand() < 0.08 ? 2.6 : 1.2, fill: "#fff", opacity: 0.25 + rand() * 0.55 }, g);
  }
  const pts = e.sparkline;
  if (pts.length) {
    const xs = pts.map((p) => p.period), ys = pts.flatMap((p) => [p.apo, p.peri]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const xr = Math.max(x1 - x0, 0.6), yr = Math.max(y1 - y0, 60);
    const xm = (x0 + x1) / 2, ym = (y0 + y1) / 2;
    const sx = (v: number) => c + ((v - xm) / xr) * R * 1.2;
    const sy = (v: number) => cy - ((v - ym) / yr) * R * 1.2;
    for (const p of pts.filter((q) => !q.parent)) {
      el("circle", { cx: sx(p.period), cy: sy(p.apo), r: 9, fill: "#d95926", opacity: 0.95 }, g);
      el("circle", { cx: sx(p.period), cy: sy(p.peri), r: 8, fill: "none", stroke: "#d95926", "stroke-width": 3, opacity: 0.85 }, g);
    }
    for (const p of pts.filter((q) => q.parent)) {
      el("circle", { cx: sx(p.period), cy: sy((p.apo + p.peri) / 2), r: 34, fill: "#3987e5", opacity: 0.18 }, g);
      el("circle", { cx: sx(p.period), cy: sy((p.apo + p.peri) / 2), r: 14, fill: "#3987e5" }, g);
    }
  }
  // frame
  el("circle", { cx: c, cy, r: R, fill: "none", stroke: TEAL_B, "stroke-width": 3, opacity: 0.8 }, svg);
  el("circle", { cx: c, cy, r: R + 14, fill: "none", stroke: GOLD_LINE, "stroke-width": 2 }, svg);
  for (let d = 0; d < 360; d += 10) {
    const a = (d * Math.PI) / 180;
    el("line", { x1: c + (R + 14) * Math.cos(a), y1: cy + (R + 14) * Math.sin(a), x2: c + (R + (d % 30 ? 22 : 30)) * Math.cos(a), y2: cy + (R + (d % 30 ? 22 : 30)) * Math.sin(a), stroke: GOLD, "stroke-width": 1.5, opacity: 0.55 }, svg);
  }
  const L = 70, m = 22;
  for (const [x, y, dx, dy] of [[m, m, 1, 1], [1000 - m, m, -1, 1], [m, 950 - m, 1, -1], [1000 - m, 950 - m, -1, -1]]) {
    el("path", { d: `M${x} ${y + dy * L} V${y} H${x + dx * L}`, fill: "none", stroke: GOLD_LINE, "stroke-width": 3 }, svg);
  }
  return svg;
}

/** Dotted world map (land sampled from the NASA Blue Marble texture) with gold breakup markers. */
export async function dottedMap(canvas: HTMLCanvasElement, marks: { lat: number; lon: number; label: string; solved: boolean }[]): Promise<void> {
  const img = new Image();
  img.src = `${BASE}textures/earth-blue-marble-2k.jpg`;
  await img.decode();
  const W = 360, H = 180;
  const off = document.createElement("canvas");
  off.width = W; off.height = H;
  const octx = off.getContext("2d", { willReadFrequently: true })!;
  octx.drawImage(img, 0, 0, W, H);
  const px = octx.getImageData(0, 0, W, H).data;
  const isLand = (lon: number, lat: number) => {
    const x = Math.min(W - 1, Math.max(0, Math.floor(((lon + 180) / 360) * W)));
    const y = Math.min(H - 1, Math.max(0, Math.floor(((90 - lat) / 180) * H)));
    const i = (y * W + x) * 4;
    const r = px[i], g = px[i + 1], b = px[i + 2];
    return r + g > b * 1.45 || r + g + b > 520;
  };
  const latTop = 82, latBot = -58;
  const draw = () => {
    const cssW = canvas.clientWidth || 800;
    const cssH = cssW * ((latTop - latBot) / 360) * 1.15;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = cssW * dpr; canvas.height = cssH * dpr;
    canvas.style.height = `${cssH}px`;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(dpr, dpr);
    const X = (lon: number) => ((lon + 180) / 360) * cssW;
    const Y = (lat: number) => ((latTop - lat) / (latTop - latBot)) * cssH;
    const step = 2.2;
    const rad = Math.max(1.1, (cssW / 360) * step * 0.34);
    ctx.fillStyle = "#5b6c88";
    let row = 0;
    for (let lat = latTop; lat >= latBot; lat -= step * 0.87, row++) {
      for (let lon = -180 + (row % 2 ? step / 2 : 0); lon < 180; lon += step) {
        if (!isLand(lon, lat)) continue;
        ctx.beginPath();
        ctx.arc(X(lon), Y(lat), rad, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    for (const m of marks) {
      const x = X(m.lon), y = Y(m.lat);
      ctx.beginPath(); ctx.arc(x, y, 11, 0, Math.PI * 2); ctx.fillStyle = "rgba(226,185,121,0.22)"; ctx.fill();
      ctx.beginPath(); ctx.arc(x, y, 5.5, 0, Math.PI * 2); ctx.fillStyle = m.solved ? GOLD : "#8d94a3"; ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = "#000"; ctx.stroke();
      ctx.font = "700 10.5px Jost, sans-serif";
      ctx.fillStyle = "#fff";
      ctx.textAlign = x > cssW * 0.8 ? "right" : "left";
      ctx.fillText(m.label.toUpperCase(), x + (x > cssW * 0.8 ? -16 : 16), y + 4);
    }
  };
  draw();
  let t = 0;
  new ResizeObserver(() => { clearTimeout(t); t = window.setTimeout(draw, 150); }).observe(canvas);
}

/** Line illustrations for the three-step strip. */
export function stepArt(kind: "collect" | "rewind" | "measure"): SVGSVGElement {
  const svg = el("svg", { viewBox: "0 0 400 320", "aria-hidden": "true" }) as SVGSVGElement;
  const c = { x: 200, y: 160 };
  if (kind === "collect") {
    el("circle", { cx: c.x, cy: c.y, r: 46, fill: "#3987e5", opacity: 0.9 }, svg);
    el("circle", { cx: c.x, cy: c.y, r: 46, fill: "none", stroke: "#9cc4f5", "stroke-width": 1.5, opacity: 0.6 }, svg);
    const rand = rng(11);
    for (let i = 0; i < 5; i++) {
      el("ellipse", { cx: c.x, cy: c.y, rx: 90 + i * 22, ry: 34 + i * 9, fill: "none", stroke: i % 2 ? TEAL_B : GOLD_LINE, "stroke-width": 1.5, transform: `rotate(${-30 + i * 17} ${c.x} ${c.y})`, opacity: 0.85 }, svg);
    }
    for (let i = 0; i < 42; i++) {
      const a = rand() * Math.PI * 2, r = 70 + rand() * 110;
      el("circle", { cx: c.x + r * Math.cos(a), cy: c.y + r * Math.sin(a) * 0.55, r: rand() < 0.2 ? 3 : 2, fill: rand() < 0.3 ? "#d95926" : GOLD }, svg);
    }
  } else if (kind === "rewind") {
    const p = { x: 200, y: 165 };
    const rand = rng(5);
    for (let i = 0; i < 16; i++) {
      const a = (i / 16) * Math.PI * 2 + rand() * 0.2, r = 120 + rand() * 30;
      const x = p.x + r * Math.cos(a), y = p.y + r * Math.sin(a) * 0.72;
      el("path", { d: `M${x} ${y} Q${(x + p.x) / 2 + 20 * Math.sin(a)} ${(y + p.y) / 2 - 20 * Math.cos(a)} ${p.x} ${p.y}`, fill: "none", stroke: i % 3 ? TEAL_B : GOLD_LINE, "stroke-width": 1.5, "stroke-dasharray": "4 5", opacity: 0.85 }, svg);
      el("circle", { cx: x, cy: y, r: 4, fill: "#d95926" }, svg);
    }
    el("circle", { cx: p.x, cy: p.y, r: 22, fill: "none", stroke: GOLD, "stroke-width": 2 }, svg);
    el("circle", { cx: p.x, cy: p.y, r: 7, fill: GOLD }, svg);
    const t = el("text", { x: p.x, y: 300, "text-anchor": "middle", fill: GOLD, "font-size": 15, "font-family": "Jost, sans-serif", "letter-spacing": 2, "font-weight": 700 }, svg);
    t.textContent = "t* · BREAKUP";
  } else {
    const o = { x: 110, y: 120 };
    const vecs = [[150, -40], [120, 30], [80, -95], [160, 70], [40, 110], [-20, -100], [100, 120]];
    for (const [dx, dy] of vecs) {
      el("line", { x1: o.x, y1: o.y, x2: o.x + dx * 0.9, y2: o.y + dy * 0.6, stroke: "#d95926", "stroke-width": 2.5 }, svg);
      el("circle", { cx: o.x + dx * 0.9, cy: o.y + dy * 0.6, r: 4, fill: "#d95926" }, svg);
    }
    el("circle", { cx: o.x, cy: o.y, r: 9, fill: "#3987e5" }, svg);
    el("path", { d: "M40 230 C 140 232, 230 240, 290 262 S 360 300, 372 312", fill: "none", stroke: GOLD, "stroke-width": 2.5 }, svg);
    el("path", { d: "M40 222 C 140 220, 240 222, 300 246 S 362 290, 376 304 L 366 316 C 350 306 330 290 290 276 S 140 246 40 240 Z", fill: GOLD, opacity: 0.12 }, svg);
    el("line", { x1: 40, y1: 300, x2: 380, y2: 300, stroke: GOLD_LINE, "stroke-width": 1.5 }, svg);
  }
  return svg;
}
