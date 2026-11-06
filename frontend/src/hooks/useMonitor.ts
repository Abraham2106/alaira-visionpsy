// Estado compartido del monitor: por cámara video, pose y riesgo; global modelos y alertas.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../config";
import { DEFAULT_CAMERA, decodeFrame } from "../frames";
import type { AlertMsg, Health, PoseMsg, ServerMsg, StatusMsg } from "../types";
import { useWebSocket } from "./useWebSocket";

export interface CameraView { frame: Blob | null; pose: PoseMsg | null; status: StatusMsg | null }
const EMPTY: CameraView = { frame: null, pose: null, status: null };

/** `cameraId` elige qué cámara se expone en frame/pose/status; `views` contiene todas. */
export function useMonitor(token: string, enabled = true, cameraId = DEFAULT_CAMERA) {
  const [views, setViews] = useState<Record<string, CameraView>>({});
  const [alerts, setAlerts] = useState<AlertMsg[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [messageError, setMessageError] = useState<string | null>(null);
  const pendingFrames = useRef<Record<string, Blob>>({});
  const patch = useCallback((id: string, change: Partial<CameraView>) =>
    setViews((previous) => ({ ...previous, [id]: { ...(previous[id] ?? EMPTY), ...change } })), []);
  // Sin id se limpian todas las cámaras (el emisor propio reinicia la vista).
  const clearFrame = useCallback((id?: string) => {
    if (id === undefined) { pendingFrames.current = {}; setViews({}); return; }
    delete pendingFrames.current[id];
    setViews((previous) => id in previous ? { ...previous, [id]: { ...previous[id], frame: null, pose: null } } : previous);
  }, []);
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
    if (event.data instanceof ArrayBuffer) {
      const packet = decodeFrame(event.data);
      if (packet) pendingFrames.current[packet.cameraId] = packet.jpeg;
      else setMessageError("Se recibió un frame inválido de la PC.");
      return;
    }
    try {
      const message = JSON.parse(event.data) as ServerMsg;
      switch (message.type) {
        case "pose": {
          // El frame solo se publica junto a su pose para no mezclar imagen nueva con esqueleto viejo.
          const frame = pendingFrames.current[message.camera_id];
          delete pendingFrames.current[message.camera_id];
          patch(message.camera_id, frame ? { pose: message, frame } : { pose: message });
          break;
        }
        case "status":
          patch(message.camera_id, { status: message });
          if (message.camera !== "streaming") clearFrame(message.camera_id);
          break;
        case "alert": updateAlert(message); break;
        case "camera_status": break; // el estado por cámara llega en cada StatusMsg
        default: throw new Error("Tipo de mensaje desconocido");
      }
    } catch { setMessageError("Se recibió un mensaje inválido de la PC."); }
  }, [clearFrame, patch, updateAlert]);

  const socket = useWebSocket("/ws/dashboard", token, onMessage, enabled);
  useEffect(() => {
    if (!socket.connected) {
      clearFrame(); setHealth(null); setAlerts([]);
      return;
    }
    let cancelled = false;
    api<Health>("/health", token).then((info) => { if (!cancelled) setHealth(info); })
      .catch((cause) => { if (!cancelled) setMessageError(cause instanceof Error ? cause.message : "No se pudo consultar el backend."); });
    return () => { cancelled = true; };
  }, [socket.connected, token, clearFrame]);

  const selected = views[cameraId] ?? EMPTY;
  return { views, frame: selected.frame, pose: selected.pose, status: selected.status, alerts, health,
    connected: socket.connected, error: socket.error || messageError, updateAlert, clearFrame, clearError };
}
