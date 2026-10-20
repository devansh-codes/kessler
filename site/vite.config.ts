import { defineConfig } from "vite";

export default defineConfig({
  base: "/kessler/",
  build: {
    target: "es2022",
    chunkSizeWarningLimit: 2500,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/three") || id.includes("globe.gl") || id.includes("three-")) return "globe";
          if (id.includes("@observablehq/plot") || id.includes("d3-")) return "plot";
          return undefined;
        },
      },
    },
  },
  optimizeDeps: { exclude: ["@duckdb/duckdb-wasm"] },
  test: { environment: "node" },
} as any);
