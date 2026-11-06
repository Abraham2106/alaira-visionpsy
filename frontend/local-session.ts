// Solo el servidor de desarrollo conoce el token; nunca se incluye en el bundle.
import { networkInterfaces } from "node:os";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";

export function localSessionAllowed(request: IncomingMessage, tls: boolean, addresses: string[]): boolean {
  const normalize = (value: string) => value.replace(/^::ffff:/, "");
  const local = new Set(["127.0.0.1", "::1", ...addresses].map(normalize));
  if (!local.has(normalize(request.socket.remoteAddress ?? ""))) return false;
  const host = request.headers.host;
  if (!host || request.headers["sec-fetch-site"] !== "same-origin") return false;
  try {
    const expected = new URL(`${tls ? "https" : "http"}://${host}`);
    const hostname = expected.hostname.replace(/^\[|\]$/g, "");
    return (hostname === "localhost" || local.has(normalize(hostname)))
      && request.headers.origin === expected.origin;
  } catch { return false; }
}

export function localSession(token: string | undefined, tls: boolean): Plugin {
  return {
    name: "local-pc-session",
    configureServer(server) {
      server.middlewares.use((request: IncomingMessage, response: ServerResponse, next) => {
        if (request.url?.split("?")[0] !== "/api/local-session") { next(); return; }
        response.setHeader("Cache-Control", "no-store");
        response.setHeader("Content-Type", "application/json");
        response.setHeader("X-Content-Type-Options", "nosniff");
        response.setHeader("Cross-Origin-Resource-Policy", "same-origin");
        response.setHeader("Vary", "Origin, Sec-Fetch-Site");
        const addresses = Object.values(networkInterfaces()).flatMap(items => items?.map(item => item.address) ?? []);
        if (request.method !== "POST" || !token || !localSessionAllowed(request, tls, addresses)) {
          response.statusCode = 403;
          response.end(JSON.stringify({ error: "Acceso automático disponible solo en esta PC" }));
          return;
        }
        response.end(JSON.stringify({ token }));
      });
    },
  };
}
