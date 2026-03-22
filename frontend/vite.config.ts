import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** Proxy distributor (docs/PORTS.md) */
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/ws": { target: "http://localhost:8000", ws: true },
      "/api": { target: "http://localhost:8000" },
    },
  },
});
