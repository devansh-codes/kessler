// Typed fetchers for the static data products. Every path goes through BASE_URL so the site
// works under the GitHub Pages project path (/kessler/).
import type { Backtest, DvRow, EphemMeta, EventIndexEntry, EventSummary, ForecastRow, GabbardRow, Manifest, Scorecard, SpaceWeather } from "./types";

export const BASE = import.meta.env.BASE_URL;
export const dataUrl = (path: string): string => `${BASE}data/${path}`;

const cache = new Map<string, Promise<unknown>>();

export class DataMissing extends Error {}

async function getJSON<T>(path: string): Promise<T> {
  if (!cache.has(path)) {
    const p = fetch(dataUrl(path)).then(async (r) => {
      if (r.status === 404) throw new DataMissing(`Data file not published yet: ${path}`);
      if (!r.ok) throw new Error(`HTTP ${r.status} for ${path}`);
      return r.json();
    });
    p.catch(() => cache.delete(path));
    cache.set(path, p);
  }
  return cache.get(path) as Promise<T>;
}

export const api = {
  manifest: () => getJSON<Manifest>("manifest.json"),
  events: () => getJSON<EventIndexEntry[]>("events/index.json"),
  event: (id: string) => getJSON<EventSummary>(`events/${id}/summary.json`),
  gabbard: (id: string) => getJSON<GabbardRow[]>(`events/${id}/gabbard.json`),
  dv: (id: string) => getJSON<DvRow[]>(`events/${id}/dv.json`),
  ephemMeta: (id: string) => getJSON<EphemMeta>(`events/${id}/ephem.meta.json`),
  ephem: async (id: string, meta: EphemMeta): Promise<Float32Array> => {
    const r = await fetch(dataUrl(`events/${id}/ephem.bin`));
    if (!r.ok) throw new Error(`HTTP ${r.status} for ephem.bin`);
    return decodeEphem(await r.arrayBuffer(), meta.T, meta.N);
  },
  forecasts: () => getJSON<ForecastRow[]>("reentry/forecasts.json"),
  backtest: () => getJSON<Backtest>("reentry/backtest.json"),
  spaceweather: () => getJSON<SpaceWeather>("spaceweather.json"),
  scorecard: () => getJSON<Scorecard>("scorecard.json"),
};

/** Decode ephem.bin: Float32 little-endian, shape [T][N][3] = (lat_deg, lon_deg, alt_km). NaN = not present. */
export function decodeEphem(buf: ArrayBuffer, T: number, N: number): Float32Array {
  const expected = T * N * 3;
  if (buf.byteLength !== expected * 4) throw new Error(`ephem.bin size ${buf.byteLength} != ${expected * 4} bytes`);
  const view = new DataView(buf);
  const out = new Float32Array(expected);
  for (let i = 0; i < expected; i++) out[i] = view.getFloat32(i * 4, true);
  return out;
}

/** Linear interpolation of one object's position between samples, handling longitude wrap. */
export function interpState(data: Float32Array, times: number[], N: number, obj: number, tSec: number): [number, number, number] | null {
  if (tSec <= times[0]) return sample(data, N, 0, obj);
  const last = times.length - 1;
  if (tSec >= times[last]) return sample(data, N, last, obj);
  let lo = 0, hi = last;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (times[mid] <= tSec) lo = mid; else hi = mid; }
  const a = sample(data, N, lo, obj), b = sample(data, N, hi, obj);
  if (!a || !b) return a ?? null;
  // sparse (daily) segments are snapshots of a fast-moving orbit: never interpolate across them
  if (times[hi] - times[lo] > 600) return a;
  const f = (tSec - times[lo]) / (times[hi] - times[lo]);
  let dLon = b[1] - a[1];
  if (dLon > 180) dLon -= 360;
  if (dLon < -180) dLon += 360;
  let lon = a[1] + dLon * f;
  if (lon > 180) lon -= 360;
  if (lon < -180) lon += 360;
  return [a[0] + (b[0] - a[0]) * f, lon, a[2] + (b[2] - a[2]) * f];
}

function sample(data: Float32Array, N: number, t: number, obj: number): [number, number, number] | null {
  const i = (t * N + obj) * 3;
  const lat = data[i];
  if (Number.isNaN(lat)) return null;
  return [lat, data[i + 1], data[i + 2]];
}
