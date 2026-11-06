// Sirve recursos locales y redirige REST/WS a la PC; HTTPS local es opcional.
import { readFileSync } from "node:fs";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { localSession } from "./local-session";

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ""), ...process.env };
  const target = env.BACKEND_URL || "http://127.0.0.1:8000";
  if (Boolean(env.LOCAL_TLS_CERT) !== Boolean(env.LOCAL_TLS_KEY)) {
    throw new Error("Configura LOCAL_TLS_CERT y LOCAL_TLS_KEY juntos");
  }
  return {
    plugins: [localSession(env.APP_TOKEN, Boolean(env.LOCAL_TLS_CERT)), react(), tailwindcss()],
    server: {
      host: "127.0.0.1", port: 5173, strictPort: true,
      https: env.LOCAL_TLS_CERT && env.LOCAL_TLS_KEY ? {
        cert: readFileSync(env.LOCAL_TLS_CERT), key: readFileSync(env.LOCAL_TLS_KEY),
      } : undefined,
      proxy: {
        "/api": { target, rewrite: (path) => path.replace(/^\/api/, "") },
        "/ws": { target, ws: true },
      },
    },
  };
});
