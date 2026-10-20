// Minimal hash router. Pages are code-split: each route lazily imports its module.
export interface PageModule {
  render(root: HTMLElement, params: Record<string, string>): Promise<(() => void) | void> | (() => void) | void;
}

type Loader = () => Promise<PageModule>;
interface Route { pattern: RegExp; keys: string[]; name: string; load: Loader; title: (p: Record<string, string>) => string }

const routes: Route[] = [];
let cleanup: (() => void) | void;
let navToken = 0;

export function route(path: string, name: string, load: Loader, title: (p: Record<string, string>) => string): void {
  const keys: string[] = [];
  const pattern = new RegExp("^" + path.replace(/:([a-zA-Z]+)/g, (_, k) => { keys.push(k); return "([^/]+)"; }) + "/?$");
  routes.push({ pattern, keys, name, load, title });
}

export function matchRoute(hash: string): { route: Route; params: Record<string, string> } | null {
  const [rawPath, query] = (hash.replace(/^#/, "") || "/").split("?");
  const path = rawPath || "/";
  for (const r of routes) {
    const m = path.match(r.pattern);
    if (m) {
      const params: Record<string, string> = {};
      r.keys.forEach((k, i) => (params[k] = decodeURIComponent(m[i + 1])));
      new URLSearchParams(query ?? "").forEach((v, k) => (params[k] = v));
      return { route: r, params };
    }
  }
  return null;
}

export async function navigate(root: HTMLElement): Promise<void> {
  const token = ++navToken;
  const found = matchRoute(location.hash) ?? matchRoute("#/")!;
  if (typeof cleanup === "function") { try { cleanup(); } catch { /* ignore */ } }
  cleanup = undefined;
  document.querySelectorAll<HTMLAnchorElement>(".nav a, .top-actions a").forEach((a) => {
    if (a.dataset.route === found.route.name || (found.route.name === "event" && a.dataset.route === "home")) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  document.title = `${found.route.title(found.params)} · Kessler`;
  root.replaceChildren();
  root.setAttribute("aria-busy", "true");
  try {
    const mod = await found.route.load();
    if (token !== navToken) return;
    const c = await mod.render(root, found.params);
    if (token !== navToken) { if (typeof c === "function") c(); return; }
    cleanup = c;
  } catch (err) {
    console.error(err);
    const msg = err instanceof Error ? err.message : String(err);
    root.innerHTML = "";
    const box = document.createElement("div");
    box.className = "wrap section";
    box.innerHTML = `<div class="error-box" role="alert"><strong>Something went wrong.</strong> <span></span></div>`;
    box.querySelector("span")!.textContent = msg;
    root.appendChild(box);
  } finally {
    root.removeAttribute("aria-busy");
  }
  window.scrollTo(0, 0);
}
