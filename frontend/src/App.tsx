// Monitor local, acceso por token de sesión y captura de la cámara de PC.
import { useEffect, useState, useSyncExternalStore, type ComponentType } from "react";
import { Activity, Video, LogOut, ChevronLeft, ShieldCheck, Radio, MapPin, Users, History } from "lucide-react";
import * as Tooltip from "@radix-ui/react-tooltip";
import AlertBanner from "./components/AlertBanner";
import AlertPanel from "./components/AlertPanel";
import CameraSender from "./components/CameraSender";
import MonitorDetails from "./components/MonitorDetails";
import VisionChat from "./components/VisionChat";
import VideoCanvas from "./components/VideoCanvas";
import ZoneEditor from "./components/ZoneEditor";
import FamilySettings from "./components/FamilySettings";
import MobileCamera from "./components/MobileCamera";
import EventHistory from "./components/EventHistory";
import { useCameras } from "./hooks/useCameras";
import { useMonitor } from "./hooks/useMonitor";
import { DEFAULT_CAMERA } from "./frames";
import { monitorTitle, worstStatus } from "./monitorStatus";

function subscribeHash(change: () => void) {
  window.addEventListener("hashchange", change);
  return () => window.removeEventListener("hashchange", change);
}

const readHash = () => location.hash.split("?")[0];

function Dashboard({ token }: { token: string }) {
  const { views, alerts, health, connected, error, updateAlert } = useMonitor(token);
  const { cameras, names } = useCameras(token);
  // Una instalación sin lista de cámaras sigue mostrando cam-1; los ids que llegan por WebSocket se añaden.
  const ids = cameras.length ? cameras.map((camera) => camera.id) : [DEFAULT_CAMERA];
  for (const id of Object.keys(views)) if (!ids.includes(id)) ids.push(id);
  const live = ids.filter((id) => views[id]?.status?.camera === "streaming");
  const primary = live[0] ?? ids[0];
  const status = worstStatus(Object.fromEntries(ids.map((id) => [id, views[id]?.status ?? null])), primary);
  const pose = views[primary]?.pose ?? null;
  const streaming = connected && live.length > 0;
  const active = alerts.filter((alert) => alert.state !== "RESOLVED").length;
  const statusTitle = monitorTitle(connected, status);
  const many = ids.length > 1;

  return <main className="dashboard">
    {error && <p className="error-box" role="alert">{error}</p>}
    <AlertBanner alerts={alerts} names={names}/>
    <div className="stats-grid">
      <div className="stat"><strong>{active}</strong><span>Alertas activas</span></div>
      <div className="stat"><strong>{alerts.length}</strong><span>Alertas de la sesión</span></div>
      <div className="stat"><strong>{pose?.landmarks?.filter(point => point[2] >= .5).length ?? 0}<small>/ 33</small></strong><span>Puntos visibles</span></div>
      <div className="stat"><strong>{many ? `${live.length}/${ids.length} en directo` : streaming ? "En directo" : "Sin señal"}</strong><span>{many ? "Cámaras" : "Cámara"}</span></div>
      <div className="stat"><strong className="stat-text">Privada</strong><span>Red local</span></div>
    </div>
    <div className="monitor-grid"><section className="monitor-main">
      <div className="panel feed-panel"><div className="panel-heading"><h2>{many ? "Cámaras" : "Cámara"}</h2><a href="#/camera" className="icon-button" aria-label="Conectar cámara de la PC"><Video size={18}/></a></div>
        {many ? <div className="video-mosaic">{ids.map((id) => {
          const view = views[id];
          const critical = view?.status?.level === "critical" && view.status.camera === "streaming";
          return <figure key={id} className={critical ? "mosaic-tile mosaic-tile-alert" : "mosaic-tile"} aria-label={`Cámara ${names[id] ?? id}`}>
            <VideoCanvas frame={view?.frame ?? null} pose={view?.pose ?? null}/>
            <figcaption><strong>{names[id] ?? id}</strong><span>{monitorTitle(connected, view?.status ?? null)}</span></figcaption>
          </figure>;
        })}</div> : <div className="monitor-stage"><VideoCanvas frame={views[primary]?.frame ?? null} pose={pose}/>
          <MonitorDetails title={statusTitle} status={status} streaming={streaming} health={health} active={active}/></div>}
        <div className="feed-footer"><span><span className="skeleton-key"/>{health?.pose === "mediapipe" ? "Pose MediaPipe" : health ? "Pose sintética" : "Pose"}</span><span>{connected ? "Conectado" : "Desconectado"}</span></div>
      </div>
      {many && <MonitorDetails title={statusTitle} status={status} streaming={streaming} health={health} active={active}/>}
    </section><aside className="monitor-aside"><AlertPanel alerts={alerts} token={token} onUpdate={updateAlert} names={names}/></aside></div>
  </main>;
}

const SCREENS: Record<string, ComponentType<{token:string}>> = {
  "#/zones":ZoneEditor, "#/family":FamilySettings, "#/events":EventHistory, "#/lab":VisionChat,
};

function PersistentCamera({token,active}:{token:string;active:boolean}) {
  const [visited,setVisited]=useState(active);
  useEffect(()=>{if(active)setVisited(true);},[active]);
  // Navigation hides the controls; only ending the session unmounts the camera owner.
  return visited ? <div hidden={!active}><CameraSender token={token} active={active}/></div> : null;
}

export default function App() {
  const [token, setToken] = useState("");
  const [draft, setDraft] = useState("");
  const hash = useSyncExternalStore(subscribeHash, readHash);
  const [access, setAccess] = useState<"loading" | "local" | "manual">("loading");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [sessionAttempt, setSessionAttempt] = useState(0);
  const phone = hash === "#/phone";
  useEffect(() => {
    if (phone) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch("/api/local-session", { method: "POST", cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error("Acceso remoto");
        const session = await response.json() as { token?: string };
        if (!session.token) throw new Error("Sesión local no disponible");
        if (!controller.signal.aborted) { setToken(session.token); setAccess("local"); }
      } catch {
        if (!controller.signal.aborted) setAccess("manual");
      }
    })();
    return () => controller.abort();
  }, [phone, sessionAttempt]);

  async function connect(event: React.FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    setLoginError(null);
    try {
      const response = await fetch("/api/health", { headers: { Authorization: `Bearer ${draft.trim()}` } });
      if (!response.ok) throw new Error(response.status === 401 ? "Token de acceso inválido." : "No se pudo conectar con la PC.");
      setToken(draft.trim()); setDraft("");
    } catch (error) { setLoginError(error instanceof Error ? error.message : "No se pudo conectar con la PC."); }
  }
  if (hash === "#/phone") return <MobileCamera/>;
  const title = {"#/camera":"Cámara de PC","#/zones":"Zonas","#/family":"Conexiones","#/events":"Historial","#/lab":"Chat de visión"}[hash] ?? "Monitor de actividad";
  const Screen=SCREENS[hash] ?? Dashboard;
  return <Tooltip.Provider delayDuration={200}><div className="app-shell">
    <aside className="sidebar"><a className="brand" href="#/" aria-label="VisionPsy-Local, inicio"><span className="brand-mark"><Activity size={24}/></span><span className="brand-name">VisionPsy</span></a>
      <nav aria-label="Principal"><span className="nav-label">GENERAL</span>
        <a className={!['#/camera','#/zones','#/family','#/events','#/lab'].includes(hash) ? "nav-item selected" : "nav-item"} href="#/"><Activity size={17}/>Monitor</a>
        <a className={hash === "#/camera" ? "nav-item selected" : "nav-item"} href="#/camera"><Video size={17}/>Cámara de PC</a>
        <a className={hash === "#/zones" ? "nav-item selected" : "nav-item"} href="#/zones"><MapPin size={17}/>Zonas</a>
        <a className={hash === "#/family" ? "nav-item selected" : "nav-item"} href="#/family"><Users size={17}/>Conexiones</a>
        <a className={hash === "#/events" ? "nav-item selected" : "nav-item"} href="#/events"><History size={17}/>Historial</a>
        <a className={hash === "#/lab" ? "nav-item selected" : "nav-item"} href="#/lab"><Video size={17}/>Chat de visión</a>
      </nav>
      <div className="sidebar-bottom"><span className="local-indicator"><ShieldCheck size={16}/>Red local</span>
        {token && <button type="button" className="nav-item" onClick={() => { setToken(""); setDraft(""); setLoginError(null); }}><LogOut size={17}/>Salir</button>}
        <span className="sidebar-note">Pose local · análisis visual pendiente</span>
      </div>
    </aside>
    <div className="workspace"><header className="site-header"><div className="header-start">
      <Tooltip.Root><Tooltip.Trigger asChild><a className="icon-button" href="#/" aria-label="Ir al monitor"><ChevronLeft size={17}/></a></Tooltip.Trigger><Tooltip.Portal><Tooltip.Content className="tooltip" sideOffset={8}>Monitor<Tooltip.Arrow/></Tooltip.Content></Tooltip.Portal></Tooltip.Root>
      <h1>{title}</h1></div>
      <div className="header-actions"><span className="today-pill">Hoy</span><span className="header-mode"><Radio size={14}/>Local</span></div>
    </header>
    {!token && access === "loading" ? <main className="login-layout"><p role="status">Conectando con esta PC…</p></main> : !token && access === "local" ? <main className="login-layout"><section className="panel login-panel">
      <h2>Sesión cerrada</h2><button type="button" className="button button-dark w-full" onClick={() => { setAccess("loading"); setSessionAttempt(attempt => attempt + 1); }}>Volver a entrar</button>
    </section></main> : !token ? <main className="login-layout"><form className="panel login-panel" onSubmit={connect}>
      <h2>Conectar</h2><p className="small-note">En la PC abre el panel local para entrar automáticamente. Para vincular un celular, abre <a href="#/phone">Cámara del celular</a>.</p>
      {loginError && <p className="error-box" role="alert">{loginError}</p>}
      <label className="field-label" htmlFor="app-token">Token de acceso</label>
      <input id="app-token" type="password" value={draft} onChange={(event) => setDraft(event.target.value)} required autoComplete="off"/>
      <button type="submit" className="button button-dark w-full" disabled={!draft.trim()}>Entrar</button></form></main>
      : <><PersistentCamera token={token} active={hash==="#/camera"}/>{hash!=="#/camera"&&<Screen token={token}/>}</>}
    </div></div></Tooltip.Provider>;
}
