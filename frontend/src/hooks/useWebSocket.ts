// Conexión autenticada con reconexión acotada y descarte de frames ante contrapresión.
import { useCallback, useEffect, useRef, useState } from "react";
import { CAPTURE, wsUrl } from "../config";

export function useWebSocket(path: "/ws/dashboard" | "/ws/ingest", token: string,
  onMessage?: (event: MessageEvent) => void, enabled = true, cameraId?: string) {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const attempt = useRef(0);
  const socket = useRef<WebSocket | null>(null);
  const inFlight = useRef(0);
  const handler = useRef(onMessage);
  useEffect(() => { handler.current = onMessage; }, [onMessage]);

  useEffect(() => {
    if (!enabled) { setConnected(false); return; }
    let stopped = false;
    let timer: number | undefined;
    setError(null);
    const ws = new WebSocket(wsUrl(path));
    // Los frames del dashboard llevan prefijo de cámara: ArrayBuffer permite decodificarlo sin esperas.
    if (path === "/ws/dashboard") ws.binaryType = "arraybuffer";
    socket.current = ws;
    inFlight.current = 0;
    ws.onopen = () => {
      if (stopped) { ws.close(); return; }
      // camera_id solo lo respeta el servidor para el token de administrador; una credencial de cámara fija la suya.
      ws.send(JSON.stringify({ type: "auth", token, flow_control: path === "/ws/ingest",
        ...(cameraId ? { camera_id: cameraId } : {}) }));
      setConnected(true);
      setError(null);
      attempt.current = 0;
    };
    ws.onmessage = (event) => {
      if(stopped) return;
      if(path === "/ws/ingest" && typeof event.data === "string") {
        try {if(JSON.parse(event.data).type === "processed") inFlight.current = 0;} catch {ws.close();}
      }
      handler.current?.(event);
    };
    ws.onerror = () => ws.close();
    ws.onclose = (event) => {
      if (stopped) return;
      setConnected(false);
      if ([1008, 1003, 1009].includes(event.code)) {
        setError(event.reason || "Conexión rechazada: revisa el token, el origen o la cámara activa.");
        return;
      }
      setError("Sin conexión con la PC. Reintentando…");
      timer = window.setTimeout(() => setRetry((value) => value + 1), Math.min(1000 * 2 ** attempt.current++, 10_000));
    };
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      ws.close();
      socket.current = null;
      inFlight.current = 0;
    };
  }, [path, token, enabled, retry, cameraId]);

  const send = useCallback((data: Blob) => {
    const ws = socket.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || ws.bufferedAmount > CAPTURE.maxBufferedBytes) return false;
    if(path === "/ws/ingest" && inFlight.current) {
      if(Date.now()-inFlight.current>4000) ws.close();
      return false;
    }
    ws.send(data);
    if(path === "/ws/ingest") inFlight.current = Date.now();
    return true;
  }, [path]);
  return { connected, error, send };
}
