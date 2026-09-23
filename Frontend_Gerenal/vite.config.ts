import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

/**
 * Dev server: start Backend on port 8000 first, then `npm run dev`.
 *
 * Both proxy entries are required for the cognitive wireup:
 *   - /api        → SSE (`/api/chat`), health probe (`/api/health`), auth endpoints.
 *   - /ws/chat    → WebSocket HITL transport.
 */

function _proxyErrHandler(label: string) {
  return (err: Error) => {
    const code = (err as NodeJS.ErrnoException).code;
    if (code === "ECONNRESET" || code === "ECONNREFUSED" || code === "ECONNABORTED") return;
    console.error(`[vite proxy ${label}]`, err.message);
  };
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  root: ".",
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("error", _proxyErrHandler("/api"));
        },
      },
      "/ws/chat": {
        target: "ws://127.0.0.1:8000",
        ws: true,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("error", _proxyErrHandler("/ws/chat"));
        },
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: "index.html",
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/__tests__/setup.ts"],
  },
});
