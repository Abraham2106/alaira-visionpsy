// Contrato idéntico a backend/messages.py y docs/ws.schema.json.
export type Level = "ok" | "suspect" | "critical";
export type AlertState = "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
export type CameraState = "waiting" | "streaming" | "disconnected";
export interface PoseMsg {
  type: "pose";
  camera_id: string;
  timestamp: number;
  landmarks: [number, number, number][] | null;
}
export interface StatusMsg {
  type: "status";
  camera_id: string;
  timestamp: number;
  level: Level;
  reasons: string[];
  camera: CameraState;
  model_error: string | null;
  diagnostics: Record<string, number | string | null> | null;
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
  sources: string[];
  zones: { revision: number; zones: { id: string; name: string; kind: "bed" | "chair" | "other"; polygon: [number, number][] }[] } | null;
}
export interface CameraStatusMsg {
  type: "camera_status";
  timestamp: number;
  cameras: Record<string, string | number | boolean | null>[];
}
export type ServerMsg = PoseMsg | StatusMsg | AlertMsg | CameraStatusMsg;
// Respuesta de GET /cameras (REST); no forma parte del contrato WebSocket.
export interface CameraInfo { id: string; name: string; state: CameraState; connected: boolean }
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
  partial_pose: "Pose parcial", pose_gap: "Postura no evaluable", fast_rotation: "Giro rápido del torso",
  falling: "Posible caída en curso", down: "Postura horizontal sostenida", upright: "Postura vertical",
  fall_transition: "Descenso y cambio de postura", fall_confirmed: "Persona posiblemente caída",
  floor_context_missing: "Falta contexto corporal para confirmar",
};
