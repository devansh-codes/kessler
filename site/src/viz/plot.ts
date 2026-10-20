// Shared Observable Plot defaults: recessive axes/grid, text tokens for ink, series colors for marks.
import * as Plot from "@observablehq/plot";

export { Plot };

export const C = {
  parent: "#3987e5",
  frag: "#d95926",
  prior: "#199e70",
  ref: "#c98500",
  alt: "#d55181",
  muted: "#838b99",
  grid: "#262c37",
  good: "#0ca30c",
  critical: "#d03b3b",
};

export function width(el: HTMLElement, fallback = 640): number {
  return Math.max(280, Math.floor(el.clientWidth || fallback));
}

export function base(w: number, h: number, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    width: w,
    height: h,
    marginLeft: 56,
    marginRight: 20,
    marginTop: 14,
    marginBottom: 36,
    style: { background: "transparent", color: "#b9bfca", fontSize: "12px", fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif", overflow: "visible" },
    ...extra,
  };
}

/** Render a plot into a host that re-renders on resize (debounced). */
export function responsive(host: HTMLElement, draw: (w: number) => Element): () => void {
  let last = -1;
  let timer: number | undefined;
  const render = () => {
    const w = width(host);
    if (Math.abs(w - last) < 8) return;
    last = w;
    host.replaceChildren(draw(w));
  };
  const ro = new ResizeObserver(() => {
    window.clearTimeout(timer);
    timer = window.setTimeout(render, 120);
  });
  ro.observe(host);
  requestAnimationFrame(render);
  return () => ro.disconnect();
}

export function legendItems(items: { label: string; color: string; ring?: boolean; line?: boolean }[]): HTMLElement {
  const el = document.createElement("div");
  el.className = "legend";
  for (const it of items) {
    const k = document.createElement("span");
    k.className = "key";
    const sw = document.createElement("i");
    if (it.line) {
      sw.style.cssText = `width:16px;height:2px;border-radius:2px;background:${it.color}`;
    } else if (it.ring) {
      sw.className = "ring";
      sw.style.color = it.color;
    } else sw.style.background = it.color;
    k.append(sw, document.createTextNode(it.label));
    el.appendChild(k);
  }
  return el;
}
