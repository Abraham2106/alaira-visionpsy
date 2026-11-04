// Monitor local, acceso por token de sesión y captura de la cámara de PC.
import { useState, useSyncExternalStore, type ComponentType } from "react";
import { Activity, Video, LogOut, ChevronLeft, ShieldCheck, Radio, MapPin, Users, History } from "lucide-react";
import * as Tooltip from "@radix-ui/react-tooltip";
import AlertBanner from "./components/AlertBanner";
import AlertPanel from "./components/AlertPanel";
import CameraSender from "./components/CameraSender";
import MonitorDetails from "./components/MonitorDetails";
import VideoCanvas from "./components/VideoCanvas";
import ZoneEditor from "./components/ZoneEditor";
import FamilySettings from "./components/FamilySettings";
import MobileCamera from "./components/MobileCamera";
import EventHistory from "./components/EventHistory";
import { useMonitor } from "./hooks/useMonitor";
import { monitorTitle } from "./monitorStatus";

function subscribeHash(change: () => void) {
  window.addEventListener("hashchange", change);
  return () => window.removeEventListener("hashchange", change);
}

const readHash = () => location.hash;

function Dashboard({ token }: { token: string }) {
  const { frame, pose, status, alerts, health, connected, error, updateAlert } = useMonitor(token);
  const streaming = connected && status?.camera === "streaming";
  const active = alerts.filter((alert) => alert.state !== "RESOLVED").length;
  const statusTitle = monitorTitle(connected, status);

  return <main className="dashboard">
    {error && <p className="error-box" role="alert">{error}</p>}
    <AlertBanner alerts={alerts}/>
    <div className="stats-grid">
      <div className="stat"><strong>{active}</strong><span>Alertas activas</span></div>
      <div className="stat"><strong>{alerts.length}</strong><span>Alertas de la sesión</span></div>
      <div className="stat"><strong>{pose?.landmarks?.filter(point => point[2] >= .5).length ?? 0}<small>/ 33</small></strong><span>Puntos visibles</span></div>
      <div className="stat"><strong>{streaming ? "En directo" : "Sin señal"}</strong><span>Cámara</span></div>
      <div className="stat"><strong className="stat-text">Privada</strong><span>Red local</span></div>
    </div>
    <div className="monitor-grid"><section className="monitor-main">
      <div className="panel feed-panel"><div className="panel-heading"><h2>Cámara</h2><a href="#/camera" className="icon-button" aria-label="Conectar cámara de la PC"><Video size={18}/></a></div>
        <VideoCanvas frame={frame} pose={pose}/>
        <div className="feed-footer"><span><span className="skeleton-key"/>{health?.pose === "mediapipe" ? "Pose MediaPipe" : health ? "Pose sintética" : "Pose"}</span><span>{connected ? "Conectado" : "Desconectado"}</span></div>
      </div>
      <MonitorDetails title={statusTitle} status={status} streaming={streaming} health={health} active={active}/>
    </section><aside className="monitor-aside"><AlertPanel alerts={alerts} token={token} onUpdate={updateAlert}/></aside></div>
  </main>;
}

const SCREENS: Record<string, ComponentType<{token:string}>> = {
  "#/camera":CameraSender, "#/zones":ZoneEditor, "#/family":FamilySettings, "#/events":EventHistory,
};

export default function App() {
  const [token, setToken] = useState("");
  const [draft, setDraft] = useState("");
  const hash = useSyncExternalStore(subscribeHash, readHash);
  if (hash === "#/phone") return <MobileCamera/>;
  const title = {"#/camera":"Cámara de PC","#/zones":"Zonas","#/family":"Conexiones","#/events":"Historial"}[hash] ?? "Monitor de actividad";
  const Screen=SCREENS[hash] ?? Dashboard;
  return <Tooltip.Provider delayDuration={200}><div className="app-shell">
    <aside className="sidebar"><a className="brand" href="#/" aria-label="VisionPsy-Local, inicio"><span className="brand-mark"><Activity size={24}/></span><span className="brand-name">VisionPsy</span></a>
      <nav aria-label="Principal"><span className="nav-label">GENERAL</span>
        <a className={!['#/camera','#/zones','#/family','#/events'].includes(hash) ? "nav-item selected" : "nav-item"} href="#/"><Activity size={17}/>Monitor</a>
        <a className={hash === "#/camera" ? "nav-item selected" : "nav-item"} href="#/camera"><Video size={17}/>Cámara de PC</a>
        <a className={hash === "#/zones" ? "nav-item selected" : "nav-item"} href="#/zones"><MapPin size={17}/>Zonas</a>
        <a className={hash === "#/family" ? "nav-item selected" : "nav-item"} href="#/family"><Users size={17}/>Conexiones</a>
        <a className={hash === "#/events" ? "nav-item selected" : "nav-item"} href="#/events"><History size={17}/>Historial</a>
      </nav>
      <div className="sidebar-bottom"><span className="local-indicator"><ShieldCheck size={16}/>Red local</span>
        {token && <button type="button" className="nav-item" onClick={() => setToken("")}><LogOut size={17}/>Salir</button>}
        <span className="sidebar-note">Pose local · análisis visual pendiente</span>
      </div>
    </aside>
    <div className="workspace"><header className="site-header"><div className="header-start">
      <Tooltip.Root><Tooltip.Trigger asChild><a className="icon-button" href="#/" aria-label="Ir al monitor"><ChevronLeft size={17}/></a></Tooltip.Trigger><Tooltip.Portal><Tooltip.Content className="tooltip" sideOffset={8}>Monitor<Tooltip.Arrow/></Tooltip.Content></Tooltip.Portal></Tooltip.Root>
      <h1>{title}</h1></div>
      <div className="header-actions"><span className="today-pill">Hoy</span><span className="header-mode"><Radio size={14}/>Local</span></div>
    </header>
    <p className="safety-note" role="note"><strong>Prototipo no médico.</strong> Puede fallar; no sustituye una llamada de emergencia.</p>
    {!token ? <main className="login-layout"><form className="panel login-panel" onSubmit={(event) => {
      event.preventDefault(); if (!draft.trim()) return; setToken(draft.trim()); setDraft("");
    }}><h2>Conectar</h2><label className="field-label" htmlFor="app-token">Token de acceso</label>
      <input id="app-token" type="password" value={draft} onChange={(event) => setDraft(event.target.value)} required autoComplete="off"/>
      <button type="submit" className="button button-dark w-full" disabled={!draft.trim()}>Entrar</button></form></main>
      : <Screen token={token}/>}
    </div></div></Tooltip.Provider>;
}
