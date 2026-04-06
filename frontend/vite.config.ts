import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** Proxy distributor (docs/PORTS.md) */
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/ws": { target: "http://127.0.0.1:8000", ws: true },
      "/api": { target: "http://127.0.0.1:8000" },
    },
  },
});
