import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy /api -> uvicorn auf Port 8000, damit das Frontend keine CORS-Probleme
// im dev hat und in prod problemlos hinter denselben Reverse-Proxy kann.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Auf Windows resolvt 'localhost' im Browser oft auf IPv4 (127.0.0.1),
    // waehrend Vite default nur auf IPv6 ([::1]) bindet -> ERR_CONNECTION_REFUSED.
    // Explizit beide Stacks bedienen.
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
