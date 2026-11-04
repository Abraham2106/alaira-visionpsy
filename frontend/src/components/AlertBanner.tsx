// Prioriza posibles caídas; entre alertas equivalentes muestra la más reciente.
import { TriangleAlert } from "lucide-react";
import { REASONS, type AlertMsg } from "../types";

export default function AlertBanner({ alerts }: { alerts: AlertMsg[] }) {
  const open = alerts.filter(alert => alert.state === "OPEN").sort((a,b) =>
    Number(b.kind === "fall") - Number(a.kind === "fall") ||
    Number(b.level === "critical") - Number(a.level === "critical") || b.timestamp - a.timestamp)[0];
  if (!open) return null;
  const time = new Date(open.timestamp * 1000).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit",
  });
  return <section className="alert-banner" role="alert" aria-live="assertive">
    <div className="alert-banner-copy">
      <span className="alert-banner-kicker"><TriangleAlert size={16}/> Alerta sin reconocer</span>
      <strong>{open.kind==="technical"?"Monitoreo interrumpido":"Posible caída detectada"}</strong>
      <p>{open.reasons.map((reason) => REASONS[reason] ?? reason).join(" · ")} · {time}</p>
    </div>
    <button type="button" className="button button-alert" onClick={() =>
      document.getElementById("alerts-heading")?.scrollIntoView({ behavior: "smooth", block: "start" })}>
      Ver y reconocer
    </button>
  </section>;
}
