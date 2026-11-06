import { useCallback, useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import { api } from "../config";
import { DEFAULT_CAMERA } from "../frames";
import { useCameras } from "../hooks/useCameras";
import type { CameraInfo } from "../types";

interface Code {code:string;expires_at:number}
interface Contact {chat_id:string;alias:string;active:number;role:"primary"|"backup"}
interface Delivery {id:number;event_id:string;kind:string;status:string;attempts:number;error:string|null}
interface Notices {enabled:boolean;error:string|null;deliveries:Delivery[]}

export default function FamilySettings({token}:{token:string}) {
  const [contacts,setContacts]=useState<Contact[]>([]);
  const [notices,setNotices]=useState<Notices|null>(null);
  const {cameras,refresh:refreshCameras}=useCameras(token);
  const [pairCamera,setPairCamera]=useState(DEFAULT_CAMERA);
  const [newCamera,setNewCamera]=useState("");
  const [cameraCodes,setCameraCodes]=useState<Record<string,Code>>({});
  const cameraCode=cameraCodes[pairCamera]??null;
  const setCameraCode=(code:Code|null)=>setCameraCodes(previous=>{
    const next={...previous};
    if(code)next[pairCamera]=code;else delete next[pairCamera];
    return next;
  });
  const [familyCode,setFamilyCode]=useState<Code|null>(null);
  const [address,setAddress]=useState(`${location.origin}/#/phone`);
  const [bot,setBot]=useState("");
  const [familyRole,setFamilyRole]=useState<"primary"|"backup">("primary");
  const [qr,setQr]=useState("");
  const [error,setError]=useState<string|null>(null);
  const [pending,setPending]=useState(false);
  const requestVersion=useRef(0);
  useEffect(()=>()=>{requestVersion.current++;},[token]);
  const refresh=useCallback(async()=>{
    try {const [people,delivery]=await Promise.all([api<Contact[]>("/contacts",token),api<Notices>("/notifications",token)]);setContacts(people);setNotices(delivery);}
    catch {setError("No se pudo consultar la vinculación.");}
  },[token]);
  useEffect(()=>{void refresh();},[refresh]);
  useEffect(()=>{
    const timer=window.setInterval(()=>{if(!document.hidden)void refreshCameras();},2000);
    return ()=>window.clearInterval(timer);
  },[refreshCameras]);
  useEffect(()=>{
    let cancelled=false;
    let url:URL;
    try {url=new URL(address);if(url.protocol!=="https:" && !(url.protocol==="http:"&&["localhost","127.0.0.1"].includes(url.hostname)))throw new Error();}
    catch {setQr("");return;}
    if(!cameraCode){setQr("");return;}
    url.username="";url.password="";url.search="";url.hash=`/phone?code=${encodeURIComponent(cameraCode.code)}`;
    QRCode.toDataURL(url.toString(),{width:220,margin:2}).then(data=>{if(!cancelled)setQr(data);}).catch(()=>{if(!cancelled)setQr("");});
    return ()=>{cancelled=true;};
  },[address,cameraCode]);
  useEffect(()=>{
    if(!cameraCode)return;
    const timer=window.setTimeout(()=>setCameraCodes(previous=>{
      if(previous[pairCamera]!==cameraCode)return previous;
      const next={...previous};delete next[pairCamera];return next;
    }),Math.max(0,cameraCode.expires_at*1000-Date.now()));
    return ()=>window.clearTimeout(timer);
  },[cameraCode,pairCamera]);
  // cam-1 conserva la ruta histórica; las demás cámaras llevan su id.
  const cameraQuery=pairCamera===DEFAULT_CAMERA?"":`?camera_id=${encodeURIComponent(pairCamera)}`;
  async function issue(purpose:"camera"|"telegram"|"telegram_backup") {
    const version=++requestVersion.current;
    setPending(true);setError(null);if(purpose==="camera"){setCameraCode(null);setQr("");}
    try {const code=await api<Code>(`/pairing/${purpose}${purpose==="camera"?cameraQuery:""}`,token,"POST");if(version!==requestVersion.current)return;if(purpose==="camera")setCameraCode(code);else setFamilyCode(code);}
    catch {if(version===requestVersion.current)setError("No se pudo generar el código.");}finally{if(version===requestVersion.current)setPending(false);}
  }
  async function remove(path:string) {
    const version=++requestVersion.current;
    setPending(true);setError(null);
    try {await api(path,token,"DELETE");if(version!==requestVersion.current)return;if(path.startsWith("/camera/pair"))setCameraCode(null);await refresh();await refreshCameras();}
    catch {if(version===requestVersion.current)setError("No se pudo desvincular.");}finally{if(version===requestVersion.current)setPending(false);}
  }
  async function addCamera() {
    const version=++requestVersion.current;
    setPending(true);setError(null);
    try {const created=await api<CameraInfo>("/cameras",token,"POST",{name:newCamera.trim()});if(version!==requestVersion.current)return;setNewCamera("");setPairCamera(created.id);setQr("");await refreshCameras();}
    catch {if(version===requestVersion.current)setError("No se pudo agregar la cámara. Revisa el nombre y el máximo permitido.");}finally{if(version===requestVersion.current)setPending(false);}
  }
  async function removeCamera(id:string) {
    const version=++requestVersion.current;
    setPending(true);setError(null);
    try {await api(`/cameras/${encodeURIComponent(id)}`,token,"DELETE");if(version!==requestVersion.current)return;
      setCameraCodes(previous=>{const next={...previous};delete next[id];return next;});
      if(pairCamera===id){setPairCamera(DEFAULT_CAMERA);setQr("");}await refreshCameras();}
    catch {if(version===requestVersion.current)setError("No se pudo quitar la cámara.");}finally{if(version===requestVersion.current)setPending(false);}
  }
  const validBot=/^[A-Za-z][A-Za-z0-9_]{4,31}bot$/i.test(bot);
  return <main className="settings-grid">
    {error&&<p className="error-box" role="alert">{error}</p>}
    <section className="panel settings-panel"><div className="panel-heading"><h2>Cámaras de la habitación</h2></div><div className="settings-body">
      <ul className="settings-list camera-list">{cameras.map(c=><li key={c.id}><span className="camera-name">{c.name}</span>
        <span className={`camera-status ${c.connected&&c.state==="streaming"?"camera-status-live":"camera-status-offline"}`}>{c.connected&&c.state==="streaming"?"En vivo":"Sin conexión"}</span>
        {c.id!==DEFAULT_CAMERA&&<button type="button" className="button button-outline" disabled={pending} onClick={()=>void removeCamera(c.id)}>Quitar cámara</button>}</li>)}</ul>
      <label htmlFor="new-camera"><strong>Nombre</strong></label><input id="new-camera" value={newCamera} maxLength={80} onChange={e=>setNewCamera(e.target.value)} placeholder="Ej. Pasillo"/>
      <button type="button" className="button button-outline" disabled={pending||!newCamera.trim()} onClick={()=>void addCamera()}>Agregar cámara</button>
    </div></section>
    <section className="panel settings-panel"><div className="panel-heading"><h2>Cámara del celular</h2></div><div className="settings-body">
      {cameras.length>1&&<><label htmlFor="pair-camera">Cámara a vincular</label><select id="pair-camera" value={pairCamera} disabled={pending} onChange={e=>{setPairCamera(e.target.value);setQr("");}}>
        {cameras.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></>}
      <label className="sr-only" htmlFor="camera-address">Dirección de cámara</label><input id="camera-address" type="url" value={address} onChange={e=>setAddress(e.target.value)}/>
      {qr&&<img className="pairing-qr" src={qr} alt="QR para vincular la cámara del celular"/>}
      <button type="button" className="button button-dark" disabled={pending} onClick={()=>void issue("camera")}>{cameraCode?"Generar nuevo QR":"Generar QR de cámara"}</button>
      {cameraCode&&<><p className="small-note" role="status">Vence a las {new Date(cameraCode.expires_at*1000).toLocaleTimeString()} · Un solo uso</p>
        <details><summary>Ingresar código manualmente</summary><code className="pairing-code">{cameraCode.code}</code></details></>}
      <button type="button" className="button button-quiet" disabled={pending} onClick={()=>void remove(`/camera/pair?camera_id=${encodeURIComponent(pairCamera)}`)}>Desvincular cámara</button>
    </div></section>
    <details className="panel settings-panel family-settings"><summary className="panel-heading"><h2>Familiares</h2><span className="disclosure-chevron" aria-hidden="true">⌄</span></summary><div className="settings-body">
      <div className="family-toolbar"><span className="small-note">{notices?.enabled ? "Telegram activo" : "Telegram sin configurar"}</span><button type="button" className="button button-quiet" onClick={()=>void refresh()}>Actualizar</button></div>
      <label htmlFor="bot-name">Usuario del bot</label><input id="bot-name" value={bot} onChange={e=>setBot(e.target.value.replace(/^@/,""))} placeholder="MiVisionPsyBot"/>
      <label htmlFor="family-role">Recibir avisos como</label><select id="family-role" name="family-role" value={familyRole} disabled={pending} onChange={e=>{setFamilyRole(e.target.value as "primary"|"backup");setFamilyCode(null);}}><option value="primary">Contacto principal</option><option value="backup">Contacto de respaldo</option></select>
      <button type="button" className="button button-dark" disabled={pending} onClick={()=>void issue(familyRole==="backup"?"telegram_backup":"telegram")}>Vincular familiar</button>
      {familyCode&&<div><p>En el chat privado del bot, envía:</p><code className="pairing-code">/start {familyCode.code}</code>
        {validBot&&<a className="button button-outline" href={`https://t.me/${bot}?start=${encodeURIComponent(familyCode.code)}`} target="_blank" rel="noreferrer">Abrir Telegram</a>}
        <p className="small-note">Código temporal. El familiar recibirá datos del evento por Telegram; no se envían imágenes.</p></div>}
      <ul className="settings-list">{contacts.filter(c=>c.active).map(c=><li key={c.chat_id}><span>{c.alias} · {c.role==="backup"?"Respaldo":"Principal"}</span><button type="button" className="button button-outline" disabled={pending} onClick={()=>void remove(`/contacts/${encodeURIComponent(c.chat_id)}`)}>Desvincular</button></li>)}</ul>
      {notices?.error&&<p className="error-box" role="alert">{notices.error}</p>}
      {Boolean(notices?.deliveries.length)&&<><h3>Últimos avisos</h3><ul className="settings-list">{notices?.deliveries.map(d=><li key={d.id}><span>Evento {d.event_id.slice(0,8)} · {d.status==="sent"?"Aceptado por Telegram":d.status==="pending"?"Pendiente":d.status==="failed"?"Falló":"Cancelado"} · {d.attempts} intentos</span>{d.error&&<span>{d.error}</span>}</li>)}</ul></>}
    </div></details>
  </main>;
}
