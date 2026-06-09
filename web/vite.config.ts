import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import legacy from "@vitejs/plugin-legacy";

// Relative base so the built bundle works served from any path (FastAPI
// /app mount) and from Capacitor/Tauri file:// origins. In dev, /api is
// proxied to the Python backend so the app talks to the real engine.
export default defineConfig({
  base: "./",
  plugins: [
    react(),
    // Emit a nomodule legacy bundle (+ polyfills) so the app runs on old
    // Android System WebViews / browsers on locked tablets, not just modern
    // engines. Modern browsers still get the lean module bundle.
    legacy({
      targets: ["chrome >= 49", "android >= 5", "ios >= 10", "safari >= 10", "defaults"],
      modernPolyfills: true,
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.AI_MUSIC_BACKEND || "http://localhost:7860",
        changeOrigin: true,
      },
      // AlphaTab JS + Bravura font + soundfont live under /static on the backend.
      "/static": {
        target: process.env.AI_MUSIC_BACKEND || "http://localhost:7860",
        changeOrigin: true,
      },
    },
  },
  // `vite preview` serves the built dist (this is what the :5174 cloudflared
  // tunnel points at). Proxy /api to the Python backend so the deployed PWA
  // talks to the real engine same-origin.
  preview: {
    host: true,          // bind 0.0.0.0 so the LAN / Tailscale phone can reach it
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.AI_MUSIC_BACKEND || "http://localhost:7860",
        changeOrigin: true,
      },
      // AlphaTab JS + Bravura font + soundfont live under /static on the backend.
      "/static": {
        target: process.env.AI_MUSIC_BACKEND || "http://localhost:7860",
        changeOrigin: true,
      },
    },
  },
  build: { outDir: "dist", sourcemap: true },
});
