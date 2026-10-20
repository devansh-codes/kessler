// globe.gl wrapper (lazy-loaded with three.js in its own chunk).
// Debris is drawn as a custom THREE.Points cloud whose position buffer is rewritten in place each
// frame, which stays fast with thousands of objects (rebuilding globe.gl layers per frame does not).
import Globe, { type GlobeInstance } from "globe.gl";
import * as THREE from "three";
import { BASE } from "../api";

const EARTH_RADIUS_KM = 6371;
const DEG = Math.PI / 180;

export interface GlobeHandle {
  globe: GlobeInstance;
  resize(): void;
  dispose(): void;
}

export function createGlobe(host: HTMLElement, opts: { autoRotate?: boolean; altitude?: number; interactive?: boolean } = {}): GlobeHandle {
  const globe = new Globe(host, { animateIn: false, rendererConfig: { antialias: true, alpha: true, powerPreference: "high-performance" } })
    .globeImageUrl(`${BASE}textures/earth-blue-marble-2k.jpg`)
    .backgroundColor("rgba(0,0,0,0)")
    .showAtmosphere(true)
    .atmosphereColor("#4f8fe0")
    .atmosphereAltitude(0.16)
    .width(host.clientWidth)
    .height(host.clientHeight);
  const mat = globe.globeMaterial() as THREE.MeshPhongMaterial;
  mat.shininess = 6;
  mat.color = new THREE.Color(0.86, 0.9, 1.0);
  globe.renderer().setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const controls = globe.controls();
  controls.autoRotate = !!opts.autoRotate;
  controls.autoRotateSpeed = 0.35;
  controls.enableZoom = opts.interactive !== false;
  controls.minDistance = 130;
  controls.maxDistance = 900;
  globe.pointOfView({ lat: 20, lng: -40, altitude: opts.altitude ?? 2.4 }, 0);

  const ro = new ResizeObserver(() => handle.resize());
  ro.observe(host);
  const handle: GlobeHandle = {
    globe,
    resize() {
      if (host.clientWidth > 0 && host.clientHeight > 0) globe.width(host.clientWidth).height(host.clientHeight);
    },
    dispose() {
      ro.disconnect();
      try { globe.pauseAnimation(); globe._destructor(); } catch { /* ignore */ }
      globe.renderer().dispose();
      host.replaceChildren();
    },
  };
  return handle;
}

function dotTexture(): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.45, "rgba(255,255,255,0.95)");
  grad.addColorStop(0.6, "rgba(255,255,255,0.35)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** A cloud of N objects with per-object color, optional trails and fade-out. */
export class DebrisLayer {
  readonly points: THREE.Points;
  readonly trails: THREE.LineSegments;
  private pos: Float32Array;
  private col: Float32Array;
  private base: Float32Array;
  private trailPos: Float32Array;
  private trailCol: Float32Array;
  readonly trailLen: number;

  constructor(private globe: GlobeInstance, readonly N: number, colors: string[], size: number, trailLen = 10) {
    this.trailLen = trailLen;
    this.pos = new Float32Array(N * 3);
    this.col = new Float32Array(N * 3);
    this.base = new Float32Array(N * 3);
    colors.forEach((hex, i) => {
      const c = new THREE.Color(hex);
      this.base.set([c.r, c.g, c.b], i * 3);
    });
    this.col.set(this.base);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(this.pos, 3).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute("color", new THREE.BufferAttribute(this.col, 3).setUsage(THREE.DynamicDrawUsage));
    const mat = new THREE.PointsMaterial({ size, vertexColors: true, map: dotTexture(), transparent: true, depthWrite: false, sizeAttenuation: true, alphaTest: 0.02 });
    this.points = new THREE.Points(geo, mat);
    this.points.frustumCulled = false;

    const segs = N * Math.max(trailLen - 1, 0);
    this.trailPos = new Float32Array(segs * 6);
    this.trailCol = new Float32Array(segs * 6);
    const tg = new THREE.BufferGeometry();
    tg.setAttribute("position", new THREE.BufferAttribute(this.trailPos, 3).setUsage(THREE.DynamicDrawUsage));
    tg.setAttribute("color", new THREE.BufferAttribute(this.trailCol, 3).setUsage(THREE.DynamicDrawUsage));
    this.trails = new THREE.LineSegments(tg, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.55, depthWrite: false }));
    this.trails.frustumCulled = false;
    globe.scene().add(this.trails);
    globe.scene().add(this.points);
    this.calibrate();
  }

  // Inline copy of three-globe's polar2Cartesian (radius 100); verified against getCoords() at startup.
  private R = 100;
  private xyz(lat: number, lon: number, altKm: number): { x: number; y: number; z: number } {
    const phi = (90 - lat) * DEG, theta = (90 - lon) * DEG, r = this.R * (1 + altKm / EARTH_RADIUS_KM);
    const sp = Math.sin(phi);
    return { x: r * sp * Math.cos(theta), y: r * Math.cos(phi), z: r * sp * Math.sin(theta) };
  }

  private calibrate(): void {
    const ref = this.globe.getCoords(10, 20, 0.1);
    const mine = this.xyz(10, 20, 0.1 * EARTH_RADIUS_KM);
    if (Math.hypot(ref.x - mine.x, ref.y - mine.y, ref.z - mine.z) > 1e-6) {
      // fall back to the library if its convention ever changes
      this.xyz = (lat, lon, altKm) => this.globe.getCoords(lat, lon, altKm / EARTH_RADIUS_KM);
    }
  }

  /** states[i] = [lat, lon, alt] or null (hidden). fade[i] in [0,1] multiplies brightness. */
  update(states: ([number, number, number] | null)[], fade?: Float32Array, trail?: ([number, number, number] | null)[][]): void {
    for (let i = 0; i < this.N; i++) {
      const s = states[i];
      const f = fade ? fade[i] : 1;
      if (!s || f <= 0) {
        this.pos.set([0, 0, 0], i * 3);
        this.col.set([0, 0, 0], i * 3);
        continue;
      }
      const p = this.xyz(s[0], s[1], s[2]);
      this.pos.set([p.x, p.y, p.z], i * 3);
      this.col.set([this.base[i * 3] * f, this.base[i * 3 + 1] * f, this.base[i * 3 + 2] * f], i * 3);
    }
    const g = this.points.geometry;
    g.attributes.position.needsUpdate = true;
    g.attributes.color.needsUpdate = true;

    const K = this.trailLen;
    if (trail && K > 1) {
      let w = 0;
      for (let i = 0; i < this.N; i++) {
        const pts = trail[i] ?? [];
        const f = fade ? fade[i] : 1;
        for (let k = 0; k < K - 1; k++) {
          const a = pts[k], b = pts[k + 1];
          const o = w * 6;
          if (a && b && f > 0 && Math.abs(a[1] - b[1]) < 90) {
            const pa = this.xyz(a[0], a[1], a[2]), pb = this.xyz(b[0], b[1], b[2]);
            this.trailPos.set([pa.x, pa.y, pa.z, pb.x, pb.y, pb.z], o);
            const ia = (k / (K - 1)) * f, ib = ((k + 1) / (K - 1)) * f;
            this.trailCol.set([this.base[i * 3] * ia, this.base[i * 3 + 1] * ia, this.base[i * 3 + 2] * ia, this.base[i * 3] * ib, this.base[i * 3 + 1] * ib, this.base[i * 3 + 2] * ib], o);
          } else {
            this.trailPos.fill(0, o, o + 6);
            this.trailCol.fill(0, o, o + 6);
          }
          w++;
        }
      }
      const tg = this.trails.geometry;
      tg.attributes.position.needsUpdate = true;
      tg.attributes.color.needsUpdate = true;
    }
  }

  dispose(): void {
    this.globe.scene().remove(this.points);
    this.globe.scene().remove(this.trails);
    this.points.geometry.dispose();
    (this.points.material as THREE.Material).dispose();
    this.trails.geometry.dispose();
    (this.trails.material as THREE.Material).dispose();
  }
}
