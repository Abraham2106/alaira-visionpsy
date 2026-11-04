import type { StatusMsg } from "./types";

const LEVEL_LABEL = { ok: "Sin señales de caída", suspect: "Revisar la escena", critical: "Posible caída" };

export function monitorTitle(connected: boolean, status: StatusMsg | null) {
  if (!connected) return "Monitor desconectado";
  if (status?.model_error) return "Revisar el modelo";
  if (status?.camera !== "streaming") return "Esperando señal de cámara";
  if (status.reasons.includes("no_pose")) return "Pose ausente o insuficiente";
  if (status.reasons.includes("insufficient_history")) return "Datos temporales insuficientes";
  return LEVEL_LABEL[status.level];
}
