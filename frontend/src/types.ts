// Contrato idéntico a backend/messages.py y docs/ws.schema.json.
export type Level = "ok" | "suspect" | "critical";
export type AlertState = "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
export type CameraState = "waiting" | "streaming" | "disconnected";
export interface PoseMsg {
  type: "pose";
  timestamp: number;
  landmarks: [number, number, number][] | null;
}
export interface StatusMsg {
  type: "status";
  timestamp: number;
  level: Level;
  reasons: string[];
  camera: CameraState;
  model_error: string | null;
}
export interface AlertMsg {
  type: "alert";
  id: string;
  timestamp: number;
  updated_at: number;
  level: Level;
  reasons: string[];
  state: AlertState;
  event: "acknowledge" | "auto_resolve" | "expire" | null;
  vision: string | null;
  vision_error: string | null;
  attention: "pending" | "attending" | "discarded" | "closed" | "expired";
  recovery_at: number | null;
  kind: "fall" | "technical";
}
export type ServerMsg = PoseMsg | StatusMsg | AlertMsg;
export interface Health {
  status: "ok";
  name: "VisionPsy-Local";
  pose: string;
  vision: string;
  scenario: string;
  synthetic: boolean;
}
export const REASONS: Record<string, string> = {
  horizontal_torso: "Torso horizontal", fast_hip_drop: "Descenso rápido de cadera",
  immobile: "Inmovilidad", safe_zone: "Dentro de zona segura", no_pose: "Sin pose visible",
  insufficient_history: "Capacidad temporal insuficiente",
  model_error: "Error del modelo", camera_disconnected: "Cámara desconectada",
};
