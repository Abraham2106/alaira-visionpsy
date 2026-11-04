import { REASONS, type Health, type StatusMsg } from "../types";

const MODEL_LABEL: Record<string, string> = {
  stub: "Sintética", mediapipe: "MediaPipe", llamacpp: "llama.cpp", qvac: "QVAC",
};

export default function MonitorDetails({ title, status, streaming, health, active }:
  { title: string; status: StatusMsg | null; streaming: boolean; health: Health | null; active: number }) {
  const severity = streaming ? status?.level : "idle";
  const vision = health ? `${MODEL_LABEL[health.vision] ?? health.vision}${health.vision === "stub" ? " (pendiente)" : ""}` : "—";
  return <div className="detail-grid">
    <section className={`panel assessment assessment-${severity}`} aria-live="polite">
      <div className="panel-heading"><h2>Estado</h2></div>
      <div className="detail-body"><h3>{title}</h3>
        {status?.model_error && <p className="error-text">{status.model_error}</p>}
        {streaming && status?.reasons.map((reason) => <span className="reason-tag" key={reason}>{REASONS[reason] ?? reason}</span>)}
      </div>
    </section>
    <section className="panel"><div className="panel-heading"><h2>Sistema</h2></div>
      <dl className="system-facts"><div><dt>Pose</dt><dd>{health ? MODEL_LABEL[health.pose] ?? health.pose : "—"}</dd></div>
        <div><dt>Visión</dt><dd>{vision}</dd></div>
        <div><dt>Alertas activas</dt><dd>{active}</dd></div>
        <div><dt>Grabación</dt><dd>Desactivada</dd></div></dl>
    </section>
  </div>;
}
