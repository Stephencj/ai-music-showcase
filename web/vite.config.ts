import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative base so the built bundle works served from any path (FastAPI
// /app mount) and from Capacitor/Tauri file:// origins. In dev, /api is
// proxied to the Python backend so the app talks to the real engine.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
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
    },
  },
  build: { outDir: "dist", sourcemap: true },
});
