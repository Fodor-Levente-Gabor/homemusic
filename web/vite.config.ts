import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  define: { __BUILD__: JSON.stringify(new Date().toISOString().slice(0, 16).replace("T", " ")) },
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8080",
      "/ws": { target: "ws://localhost:8080", ws: true },
    },
  },
});
