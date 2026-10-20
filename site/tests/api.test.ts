import { describe, expect, it } from "vitest";
import { decodeEphem, interpState } from "../src/api";
import { matchRoute, route } from "../src/router";

function encode(values: number[]): ArrayBuffer {
  const buf = new ArrayBuffer(values.length * 4);
  const v = new DataView(buf);
  values.forEach((x, i) => v.setFloat32(i * 4, x, true));
  return buf;
}

describe("ephem.bin decoder", () => {
  it("decodes little-endian float32 [T][N][3]", () => {
    // T=2, N=2
    const vals = [10, 20, 500, 11, 21, 600, 12, 22, 501, NaN, NaN, NaN];
    const out = decodeEphem(encode(vals), 2, 2);
    expect(out.length).toBe(12);
    expect(out[0]).toBeCloseTo(10);
    expect(out[5]).toBeCloseTo(600);
    expect(Number.isNaN(out[9])).toBe(true);
  });

  it("rejects a buffer of the wrong size", () => {
    expect(() => decodeEphem(encode([1, 2, 3]), 2, 2)).toThrow(/size/);
  });
});

describe("interpolation", () => {
  const data = new Float32Array([0, 170, 500, 10, -170, 520, 0, 0, 0]); // T=3, N=1
  const times = [0, 120, 86400];

  it("interpolates across the antimeridian the short way", () => {
    const s = interpState(data, times, 1, 0, 60)!;
    expect(s[0]).toBeCloseTo(5);
    expect(Math.abs(s[1])).toBeCloseTo(180);
    expect(s[2]).toBeCloseTo(510);
  });

  it("does not interpolate across sparse daily gaps", () => {
    const s = interpState(data, times, 1, 0, 40000)!;
    expect(s[0]).toBeCloseTo(10);
  });

  it("clamps outside the sampled range", () => {
    expect(interpState(data, times, 1, 0, -5)![2]).toBeCloseTo(500);
  });
});

describe("router", () => {
  it("matches event routes with params", () => {
    route("/event/:id", "event", async () => ({ render: () => undefined }), () => "");
    const m = matchRoute("#/event/usa-32");
    expect(m?.route.name).toBe("event");
    expect(m?.params.id).toBe("usa-32");
  });
});
