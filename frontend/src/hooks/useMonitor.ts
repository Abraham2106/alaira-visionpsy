// Estado compartido del monitor: video, pose, riesgo, modelos y alertas.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../config";
import type { AlertMsg, Health, PoseMsg, ServerMsg, StatusMsg } from "../types";
import { useWebSocket } from "./useWebSocket";

export function useMonitor(token: string, enabled = true) {
  const [frame, setFrame] = useState<Blob | null>(null);
  const [pose, setPose] = useState<PoseMsg | null>(null);
  const [status, setStatus] = useState<StatusMsg | null>(null);
  const [alerts, setAlerts] = useState<AlertMsg[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [messageError, setMessageError] = useState<string | null>(null);
  const pendingFrame = useRef<Blob|null>(null);
  const clearFrame = useCallback(() => { pendingFrame.current=null; setFrame(null); setPose(null); }, []);
  const clearError = useCallback(() => setMessageError(null), []);

  const updateAlert = useCallback((alert: AlertMsg) => {
    setAlerts((previous) => {
      const existing = previous.find((item) => item.id === alert.id);
      if (existing && existing.updated_at > alert.updated_at) return previous;
      const next = existing ? previous.map((item) => item.id === alert.id ? alert : item) : [...previous, alert];
      return next.slice(-100);
    });
  }, []);

  const onMessage = useCallback((event: MessageEvent) => {
    if (event.data instanceof Blob) { pendingFrame.current=event.data; return; }
    try {
      const message = JSON.parse(event.data) as ServerMsg;
      switch (message.type) {
        case "pose":
          setPose(message);
          if(pendingFrame.current) {setFrame(pendingFrame.current);pendingFrame.current=null;}
          break;
        case "status":
          setStatus(message);
          if (message.camera !== "streaming") clearFrame();
          break;
        case "alert": updateAlert(message); break;
        default: throw new Error("Tipo de mensaje desconocido");
      }
    } catch { setMessageError("Se recibió un mensaje inválido de la PC."); }
  }, [clearFrame, updateAlert]);

  const socket = useWebSocket("/ws/dashboard", token, onMessage, enabled);
  useEffect(() => {
    if (!socket.connected) {
      clearFrame(); setStatus(null); setHealth(null); setAlerts([]);
      return;
    }
    let cancelled = false;
    api<Health>("/health", token).then((info) => { if (!cancelled) setHealth(info); })
      .catch((cause) => { if (!cancelled) setMessageError(cause instanceof Error ? cause.message : "No se pudo consultar el backend."); });
    return () => { cancelled = true; };
  }, [socket.connected, token, clearFrame]);

  return { frame, pose, status, alerts, health, connected: socket.connected,
    error: socket.error || messageError, updateAlert, clearFrame, clearError };
}
