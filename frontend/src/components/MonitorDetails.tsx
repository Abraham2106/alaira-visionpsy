import { REASONS, type Health, type StatusMsg } from "../types";

const MODEL_LABEL: Record<string, string> = {
  stub: "Sintética", mediapipe: "MediaPipe", llamacpp: "llama.cpp", qvac: "QVAC",
};

function DetectorDiagnostics({diagnostics}:{diagnostics:Record<string,number|string|null>}) {
  return <details className="detector-diagnostics"><summary>Diagnóstico</summary><dl>
    <div><dt>Estado</dt><dd>{String(diagnostics.phase ?? "—")}</dd></div>
    <div><dt>Pose</dt><dd>{({complete:"Completa",partial:"Parcial",missing:"No evaluable"} as Record<string,string>)[String(diagnostics.quality)] ?? "—"}</dd></div>
    <div><dt>Torso</dt><dd>{diagnostics.angle_deg ?? "—"}°</dd></div>
    <div><dt>Descenso</dt><dd>{diagnostics.vertical_speed ?? "—"} torsos/s</dd></div>
    <div><dt>Giro</dt><dd>{diagnostics.angular_speed ?? "—"}°/s</dd></div>
    <div><dt>Evidencia</dt><dd>{diagnostics.observed_seconds ?? 0} s</dd></div>
    <div><dt>Procesamiento</dt><dd>{diagnostics.fps ?? "—"} FPS · {diagnostics.latency_ms ?? "—"} ms</dd></div>
  </dl></details>;
}

export default function MonitorDetails({ title, status, streaming, health, active }:
  { title: string; status: StatusMsg | null; streaming: boolean; health: Health | null; active: number }) {
  const severity = streaming && !status?.reasons.includes("no_pose") ? status?.level : "idle";
  const diagnostics = status?.diagnostics;
  const vision = health ? `${MODEL_LABEL[health.vision] ?? health.vision}${health.vision === "stub" ? " (pendiente)" : ""}` : "—";
  return <div className="detail-grid">
    <section className={`panel assessment assessment-${severity}`} aria-live="polite">
      <div className="panel-heading"><h2>Estado</h2></div>
      <div className="detail-body"><h3>{title}</h3>
        {status?.model_error && <p className="error-text">{status.model_error}</p>}
        {streaming && status?.reasons.map((reason) => <span className="reason-tag" key={reason}>{REASONS[reason] ?? reason}</span>)}
        {diagnostics && <DetectorDiagnostics diagnostics={diagnostics}/>}
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
