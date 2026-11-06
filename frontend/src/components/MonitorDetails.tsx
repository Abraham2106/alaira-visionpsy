import type { Health, StatusMsg } from "../types";

const MODEL_LABEL: Record<string, string> = { stub: "Sintética", mediapipe: "MediaPipe", llamacpp: "llama.cpp", qvac: "QVAC" };

export default function MonitorDetails({ title, status, streaming, health, active }:
  { title: string; status: StatusMsg | null; streaming: boolean; health: Health | null; active: number }) {
  const data = status?.diagnostics;
  const evaluable = streaming && data?.quality !== "missing" && !status?.reasons.includes("no_pose") && !status?.model_error;
  const tone = !streaming || !evaluable ? "idle" : status?.level ?? "idle";
  const quality = !streaming ? "SIN SEÑAL" : !evaluable ? "NO EVALUABLE" : data?.quality === "partial" ? "PARCIAL" : data?.quality === "complete" ? "COMPLETA" : "—";
  const value = (key: string, unit = "") => streaming && data?.[key] != null ? `${data[key]}${unit}` : "—";
  return <section className={`terminal-hud terminal-${tone}`} aria-label="Telemetría de cámara">
    <details open>
      <summary><span className="terminal-prompt">visionpsy.local</span><span>camera --watch</span></summary>
      <div className="terminal-content">
        <div className="terminal-session"><span className="terminal-link">[{streaming ? "live" : "offline"}]</span> cámara {status?.camera_id ?? "—"}</div>
        <div className="terminal-state"><span>status:</span><strong>{evaluable ? String(data?.phase ?? status?.level ?? "—") : quality}</strong></div>
        <p className="terminal-message" role="status">[{title}]</p>
        {status?.model_error && <p className="terminal-error">{status.model_error}</p>}
        <dl className="terminal-metrics">
          <div><dt>pose</dt><dd>{quality}</dd></div>
          <div><dt>torso</dt><dd>{evaluable ? value("angle_deg", "°") : "—"}</dd></div>
          <div><dt>descenso</dt><dd>{evaluable ? value("vertical_speed", " torsos/s") : "—"}</dd></div>
          <div><dt>giro</dt><dd>{evaluable ? value("angular_speed", "°/s") : "—"}</dd></div>
          <div><dt>evidencia</dt><dd>{value("observed_seconds", " s")}</dd></div>
          <div className="terminal-performance"><dt>proceso</dt><dd>{value("fps", " FPS")} <span> / </span>{value("latency_ms", " ms")}</dd></div>
        </dl>
        <div className="terminal-system"><span>pose <b>{health ? MODEL_LABEL[health.pose] ?? health.pose : "—"}</b></span><span>visión <b>{health ? MODEL_LABEL[health.vision] ?? health.vision : "—"}</b></span></div>
        <div className="terminal-bottom"><span>ALERTAS <b>{active}</b></span><span>REC <b>OFF</b></span></div>
      </div>
    </details>
  </section>;
}
