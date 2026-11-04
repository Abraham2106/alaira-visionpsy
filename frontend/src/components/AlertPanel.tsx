// Historial de alertas con reconocimiento REST y estados de envío y error por alerta.
import { useState } from "react";
import { TriangleAlert } from "lucide-react";
import { api } from "../config";
import { REASONS, type AlertMsg, type AlertState } from "../types";

const STATE_LABEL = { OPEN: "Sin reconocer", ACKNOWLEDGED: "Reconocida", RESOLVED: "Resuelta" };
const STATE_ORDER: Record<AlertState, number> = { OPEN: 0, ACKNOWLEDGED: 1, RESOLVED: 2 };
const EVENT_LABEL = { acknowledge: "Reconocida por el usuario", auto_resolve: "Resuelta por recuperación",
  expire: "Tiempo de vigilancia agotado" };
const ATTENTION_LABEL = {pending:"Sin atención confirmada",attending:"Alguien está atendiendo",discarded:"Descartada por el cuidador",closed:"Cerrada por el cuidador",expired:"Expirada sin atención confirmada"};

function visionText(alert: AlertMsg) {
  if (alert.vision_error) return alert.vision_error;
  if (alert.vision?.startsWith("[stub]")) return "Respuesta sintética: la imagen no fue evaluada por IA.";
  return alert.vision ?? "Analizando la imagen…";
}

function AlertItem({ alert, token, onUpdate }: { alert: AlertMsg; token: string; onUpdate: (alert: AlertMsg) => void }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  async function act(action:"attend"|"discard"|"close") {
    setPending(true); setError(null);
    try { onUpdate(await api<AlertMsg>(`/alerts/${alert.id}/action`, token, "POST",{action,reason})); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "No se pudo reconocer la alerta."); }
    finally { setPending(false); }
  }
  return <li className={`alert-item alert-${alert.state.toLowerCase()}`}>
    <div className="alert-item-head"><span className="alert-state">{alert.event==="expire"?"Expirada":STATE_LABEL[alert.state]}</span>
      <time dateTime={new Date(alert.timestamp * 1000).toISOString()}>
        {new Date(alert.timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
      </time></div>
    <h3>{alert.state === "OPEN" && <TriangleAlert size={17} aria-hidden="true"/>}{alert.kind==="technical"?"Monitoreo interrumpido":"Posible caída"}</h3>
    <p>{alert.reasons.map((reason) => REASONS[reason] ?? reason).join(" · ")}</p>
    <p>{ATTENTION_LABEL[alert.attention ?? "pending"]}</p>
    {alert.kind!=="technical"&&<div className="vision-note"><span className="vision-label">Análisis visual</span><span>{visionText(alert)}</span></div>}
    {alert.event && <p className="event-note">{alert.kind==="technical"&&alert.event==="auto_resolve"?"Señal recuperada":EVENT_LABEL[alert.event]}</p>}
    {!['closed','discarded'].includes(alert.attention) && <div className="event-actions">
      {alert.attention!=="attending"&&<button type="button" className="button button-dark w-full" disabled={pending} onClick={()=>void act("attend")}>{pending?"Registrando…":"Estoy atendiendo"}</button>}
      <label htmlFor={`reason-${alert.id}`}>Motivo de descarte</label><input id={`reason-${alert.id}`} value={reason} maxLength={300} onChange={e=>setReason(e.target.value)}/>
      <div className="button-row"><button type="button" className="button button-outline" disabled={pending||!reason.trim()} onClick={()=>void act("discard")}>Descartar</button>
        <button type="button" className="button button-outline" disabled={pending} onClick={()=>void act("close")}>Cerrar evento</button></div>
    </div>}
    {error && <p className="error-text" role="alert">{error}</p>}
  </li>;
}

export default function AlertPanel(props: { alerts: AlertMsg[]; token: string; onUpdate: (alert: AlertMsg) => void }) {
  const open = props.alerts.filter((alert) => alert.state === "OPEN").length;
  const ordered = [...props.alerts].sort((left, right) =>
    STATE_ORDER[left.state] - STATE_ORDER[right.state] || right.timestamp - left.timestamp);
  return <section className="panel alerts-panel" aria-labelledby="alerts-heading">
    <div className="panel-heading"><h2 id="alerts-heading">Alertas</h2>
      <span className={open ? "count count-alert" : "count"}>{open ? `${open} sin reconocer` : `${props.alerts.length} en sesión`}</span></div>
    {ordered.length ? <ul className="alert-list">{ordered.map((alert) =>
      <AlertItem key={alert.id} alert={alert} token={props.token} onUpdate={props.onUpdate} />)}</ul>
      : <div className="alerts-empty"><span className="empty-check" aria-hidden="true">✓</span>
        <h3>Sin alertas por ahora</h3></div>}
  </section>;
}
