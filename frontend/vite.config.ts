import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: the frontend runs on 5173 and proxies /api to the FastAPI server on
// 8765. Build: output goes into the Python package so FastAPI serves it in a
// packaged app.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8765" },
  },
  build: {
    outDir: "../seshat/api/static",
    emptyOutDir: true,
  },
});
