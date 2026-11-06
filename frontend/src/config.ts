// URLs del mismo origen: el proxy local evita puertos y tokens incrustados en el navegador.
export const CAPTURE = { fps: 24, maxWidth: 800, quality: 0.65, maxBufferedBytes: 2_000_000 };

export function wsUrl(path: "/ws/dashboard" | "/ws/ingest"): string {
  const url = new URL(path, location.origin);
  url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export async function api<T>(path: string, token: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, { method, headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : {"Content-Type":"application/json"}) },
    body: body === undefined ? undefined : JSON.stringify(body) });
  if (!response.ok) {
    throw new Error(response.status === 401 ? "Token inválido. Cierra la sesión y vuelve a conectar."
      : response.status === 409 ? "La alerta ya cambió de estado."
      : `No se pudo completar la solicitud (${response.status}).`);
  }
  return response.json() as Promise<T>;
}
