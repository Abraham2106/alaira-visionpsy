import { useCallback, useEffect, useRef, useState } from "react";
import { useCameraCapture } from "../hooks/useCameraCapture";
import { useWebSocket } from "../hooks/useWebSocket";

interface Pairing {token:string;camera_id?:string}
const readCode=()=>new URLSearchParams(location.hash.split("?")[1]??"").get("code")??"";
async function exchange(code:string):Promise<Pairing> {
  const result=await fetch("/api/camera/pair",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code:code.trim()})});
  if(!result.ok)throw new Error(result.status===429?"Espera un minuto antes de reintentar.":"QR inválido o vencido. Genera uno nuevo en la PC.");
  return result.json() as Promise<Pairing>;
}

export default function MobileCamera() {
  const [qrCode,setQrCode]=useState(readCode);
  const automatic=useRef<{code:string;promise:Promise<Pairing>}|null>(null);
  const [code,setCode]=useState("");
  const [token,setToken]=useState("");
  const [cameraId,setCameraId]=useState("");
  const [running,setRunning]=useState(false);
  const [consent,setConsent]=useState(false);
  const [pending,setPending]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const ingest=useWebSocket("/ws/ingest",token,undefined,running&&Boolean(token));
  const fail=useCallback((message:string)=>{setError(message);setRunning(false);},[]);
  const {videoRef,captureRef,frames,resetFrames}=useCameraCapture("camera",running,ingest.send,fail);
  useEffect(()=>{
    const scanned=()=>{const next=readCode();if(next)setQrCode(next);};
    window.addEventListener("hashchange",scanned);
    return ()=>window.removeEventListener("hashchange",scanned);
  },[]);
  useEffect(()=>{
    if(!qrCode)return;
    // El código viaja en el fragmento: no se envía en la petición de la página ni queda en la URL.
    history.replaceState(history.state,"",`${location.pathname}${location.search}#/phone`);
    let cancelled=false;
    setPending(true);setError(null);setRunning(false);setToken("");setConsent(false);
    if(automatic.current?.code!==qrCode)automatic.current={code:qrCode,promise:exchange(qrCode)};
    automatic.current.promise.then(body=>{
      if(cancelled)return;
      setToken(body.token);setCameraId(body.camera_id??"");setCode("");
    }).catch(cause=>{
      if(!cancelled)setError(cause instanceof Error?cause.message:"No se pudo vincular.");
    }).finally(()=>{if(!cancelled)setPending(false);});
    return ()=>{cancelled=true;};
  },[qrCode]);
  async function pair(event:React.FormEvent) {
    event.preventDefault();setPending(true);setError(null);
    try {const body=await exchange(code);setToken(body.token);setCameraId(body.camera_id??"");setCode("");
    }catch(cause){setError(cause instanceof Error?cause.message:"No se pudo vincular.");}finally{setPending(false);}
  }
  return <main className="mobile-capture panel settings-panel"><div className="panel-heading"><h1>Cámara del celular</h1></div><div className="settings-body">
    {!token&&<form onSubmit={e=>void pair(e)}><label htmlFor="pair-code">Código de cámara</label><input id="pair-code" value={code} maxLength={100} autoComplete="off" onChange={e=>setCode(e.target.value)} required/>
      <button type="submit" className="button button-dark w-full" disabled={pending||!code.trim()}>{pending?"Vinculando…":"Vincular"}</button></form>}
    <div className="camera-preview"><video ref={videoRef} muted playsInline/><canvas ref={captureRef} hidden/>{!running&&<div className="preview-label">Captura detenida</div>}</div>
    {token&&cameraId&&<p className="small-note">Vinculada como {cameraId}.</p>}
    <p role="status">{running?(ingest.connected?"Conectada a la PC":"Reconectando…"):"Detenida"} · {frames} frames enviados</p>
    <label className="consent-control"><input type="checkbox" checked={consent} disabled={running} onChange={e=>setConsent(e.target.checked)}/>La persona supervisada consiente el uso de la cámara.</label>
    <button type="button" className="button button-dark" disabled={!token||(!running&&!consent)} onClick={()=>{setError(null);if(!running)resetFrames();setRunning(v=>!v);}}>{running?"Detener cámara":"Iniciar cámara"}</button>
    <button type="button" className="button button-outline" disabled={running||!token} onClick={()=>setToken("")}>Cambiar vinculación</button>
    {(error||ingest.error)&&<p className="error-box" role="alert">{error||ingest.error}</p>}
    <p className="small-note">Mantén esta página visible y el teléfono conectado a alimentación. Sin audio ni grabación continua. La inferencia se realiza en la PC.</p>
  </div></main>;
}
