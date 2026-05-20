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
  build: { outDir: "dist", sourcemap: true },
});
