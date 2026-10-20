// Fails the build if the JS loaded on first paint exceeds 250 KB gzipped.
// Lazy chunks (globe/three, plot, duckdb, per-page modules) are excluded: they load on demand.
import { readFileSync, readdirSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

const dist = new URL("../dist/", import.meta.url).pathname;
const html = readFileSync(join(dist, "index.html"), "utf8");
const initial = new Set([...html.matchAll(/(?:src|href)="[^"]*\/(assets\/[^"]+\.js)"/g)].map((m) => m[1]));
let total = 0;
for (const f of initial) {
  const gz = gzipSync(readFileSync(join(dist, f))).length;
  total += gz;
  console.log(`${f}  ${(gz / 1024).toFixed(1)} KB gz`);
}
const all = readdirSync(join(dist, "assets")).filter((f) => f.endsWith(".js"));
console.log(`initial JS: ${(total / 1024).toFixed(1)} KB gz across ${initial.size} file(s); ${all.length} chunks total`);
if (total > 250 * 1024) {
  console.error("FAIL: initial JS exceeds 250 KB gzipped");
  process.exit(1);
}
