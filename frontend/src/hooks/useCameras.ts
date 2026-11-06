// Lista de cámaras de la habitación (REST); el estado en vivo llega por el WebSocket del monitor.
import { useCallback, useEffect, useState } from "react";
import { api } from "../config";
import type { CameraInfo } from "../types";

export function useCameras(token: string, refreshKey: unknown = 0) {
  const [cameras, setCameras] = useState<CameraInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      const list = await api<CameraInfo[]>("/cameras", token);
      setCameras(Array.isArray(list) ? list : []);
      setError(null);
    } catch { setError("No se pudo consultar las cámaras."); }
  }, [token]);
  useEffect(() => { void refresh(); }, [refresh, refreshKey]);
  const names = Object.fromEntries(cameras.map((camera) => [camera.id, camera.name]));
  return { cameras, names, error, refresh };
}
