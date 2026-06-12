import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

// Standalone offline dress-up build — a self-contained static site (no backend,
// no other screens) that ships as the Android "Dress Up Band" app and/or a
// static deploy. Relative base so it works under any path / from file://.
export default defineConfig({
  base: "./",
  plugins: [react()],
  publicDir: resolve(__dirname, "dressup-public"),
  build: {
    outDir: "dist-dressup",
    emptyOutDir: true,
    rollupOptions: { input: resolve(__dirname, "dressup.html") },
  },
});
