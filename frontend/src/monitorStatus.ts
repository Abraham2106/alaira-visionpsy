import type { AlertMsg, Level, StatusMsg } from "./types";

const LEVEL_LABEL = { ok: "Sin señales de caída", suspect: "Revisar la escena", critical: "Posible caída" };
const SEVERITY: Record<Level, number> = { ok: 0, suspect: 1, critical: 2 };

export function monitorTitle(connected: boolean, status: StatusMsg | null) {
  if (!connected) return "Monitor desconectado";
  if (status?.model_error) return "Revisar el modelo";
  if (status?.camera !== "streaming") return "Esperando señal de cámara";
  if (status.reasons.includes("no_pose")) return "No evaluable: torso no visible";
  if (status.reasons.includes("insufficient_history")) return "Datos temporales insuficientes";
  return LEVEL_LABEL[status.level];
}

/** Estado más grave entre las cámaras en directo; si ninguna transmite, el de la cámara preferida. */
export function worstStatus(statuses: Record<string, StatusMsg | null | undefined>, preferred: string): StatusMsg | null {
  const live = Object.values(statuses).filter((item): item is StatusMsg => item?.camera === "streaming");
  if (!live.length) return statuses[preferred] ?? Object.values(statuses).find(Boolean) ?? null;
  return live.reduce((worst, item) => SEVERITY[item.level] > SEVERITY[worst.level] ? item : worst);
}

/** "Sala + Pasillo" cuando hay varias cámaras en la habitación; vacío con una sola. */
export function sourceLabel(alert: AlertMsg, names: Record<string, string> | undefined): string {
  if (!names || Object.keys(names).length < 2) return "";
  return (alert.sources ?? []).map((id) => names[id] ?? id).join(" + ");
}
