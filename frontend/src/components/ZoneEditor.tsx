import { useEffect, useRef, useState } from "react";
import { Plus, Trash2, Undo2, Save } from "lucide-react";
import { api } from "../config";
import { imagePoint } from "../geometry";
import { DEFAULT_CAMERA } from "../frames";
import { useCameras } from "../hooks/useCameras";
import { useMonitor } from "../hooks/useMonitor";

interface Zone { id:string; name:string; kind:"bed"|"chair"|"other"; polygon:[number,number][] }
interface Document { revision:number; zones:Zone[] }

export default function ZoneEditor({token}:{token:string}) {
  const [cameraId,setCameraId]=useState(DEFAULT_CAMERA);
  const {cameras}=useCameras(token);
  const monitor=useMonitor(token,true,cameraId);
  // cam-1 conserva la ruta histórica; las demás cámaras llevan su id.
  const zonesPath=cameraId===DEFAULT_CAMERA?"/zones":`/zones?camera_id=${encodeURIComponent(cameraId)}`;
  const [document,setDocument]=useState<Document>({revision:0,zones:[]});
  const [selected,setSelected]=useState<string|null>(null);
  const [points,setPoints]=useState<[number,number][]>([]);
  const [name,setName]=useState("Cama");
  const [kind,setKind]=useState<Zone["kind"]>("bed");
  const [source,setSource]=useState<string|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [notice,setNotice]=useState("");
  const [pending,setPending]=useState(false);
  const saveVersion=useRef(0);
  useEffect(()=>()=>{saveVersion.current++;},[token]);
  const imageRef=useRef<HTMLImageElement>(null);
  const heldFrame=useRef<Blob|null>(null);
  const [size,setSize]=useState({width:960,height:540});
  const [coordinates,setCoordinates]=useState("");

  useEffect(()=>{
    let cancelled=false;
    api<Document>(zonesPath,token).then(data=>{if(!cancelled)setDocument(data);}).catch(()=>{if(!cancelled)setError("No se pudieron cargar las zonas.");});
    return ()=>{cancelled=true;};
  },[token,zonesPath]);
  useEffect(()=>{
    if (heldFrame.current || !monitor.frame) return;
    heldFrame.current=monitor.frame;
    const url=URL.createObjectURL(monitor.frame);
    setSource(url);
    return undefined;
  },[monitor.frame]);
  useEffect(()=>()=>{if(source)URL.revokeObjectURL(source);},[source]);

  function changeCamera(id:string) {
    saveVersion.current++;heldFrame.current=null;setSource(null);setDocument({revision:0,zones:[]});setError(null);setPending(false);
    reset();setCameraId(id);
  }
  function reset() {setSelected(null);setPoints([]);setCoordinates("");setName("Cama");setKind("bed");setNotice("");}
  function choose(zone:Zone) {setSelected(zone.id);setPoints(zone.polygon);setCoordinates(zone.polygon.map(p=>p.join(",")).join("\n"));setName(zone.name);setKind(zone.kind);setNotice("");}
  async function save(remove=false) {
    const version=++saveVersion.current;
    setPending(true);setError(null);setNotice("");
    const id=selected ?? crypto.randomUUID();
    const zones=document.zones.filter(z=>z.id!==id);
    if(!remove) zones.push({id,name:name.trim(),kind,polygon:points});
    try {const saved=await api<Document>(zonesPath,token,"PUT",{revision:document.revision,zones});if(version!==saveVersion.current)return;setDocument(saved);reset();setNotice("Zonas guardadas");}
    catch {if(version===saveVersion.current)setError("No se pudo guardar. Comprueba el polígono; si otra sesión modificó las zonas, recarga.");}
    finally {if(version===saveVersion.current)setPending(false);}
  }
  return <main className="settings-grid">
    <section className="panel settings-panel">
      <div className="panel-heading"><h2>Zonas</h2><button type="button" className="icon-button" onClick={reset} aria-label="Nueva zona"><Plus size={18}/></button></div>
      <div className="zone-stage" style={{aspectRatio:`${size.width}/${size.height}`}}>
        {source ? <img ref={imageRef} src={source} alt="Imagen de referencia para delimitar zonas" onLoad={e=>setSize({width:e.currentTarget.naturalWidth,height:e.currentTarget.naturalHeight})}/>
          : <p>Conecta la cámara para capturar una referencia.</p>}
        {source && <svg viewBox={`0 0 ${size.width} ${size.height}`} aria-label="Editor de polígono" role="img" onPointerDown={e=>{
          const p=imagePoint(e.clientX,e.clientY,e.currentTarget.getBoundingClientRect(),size.width,size.height);
          if(p && points.length<32) setPoints(previous=>[...previous,p]);
        }}>
          {document.zones.filter(z=>z.id!==selected).map(z=><polygon key={z.id} points={z.polygon.map(([x,y])=>`${x*size.width},${y*size.height}`).join(" ")} className="zone-saved"/>)}
          <polyline points={points.map(([x,y])=>`${x*size.width},${y*size.height}`).join(" ")} className="zone-draft"/>
          {points.map(([x,y],i)=><circle key={i} cx={x*size.width} cy={y*size.height} r={size.width/150} fill="var(--accent)"/>)}
        </svg>}
      </div>
      <div className="settings-body">
        {cameras.length>1&&<><label htmlFor="zone-camera">Cámara</label><select id="zone-camera" value={cameraId} disabled={pending} onChange={e=>changeCamera(e.target.value)}>
          {cameras.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></>}
        <p className="small-note">Marca al menos tres puntos. La cámara debe permanecer fija.</p>
        <label htmlFor="zone-name">Nombre</label><input id="zone-name" value={name} maxLength={80} onChange={e=>setName(e.target.value)}/>
        <label htmlFor="zone-kind">Tipo</label><select id="zone-kind" value={kind} onChange={e=>setKind(e.target.value as Zone["kind"])}><option value="bed">Cama</option><option value="chair">Silla</option><option value="other">Otra</option></select>
        <details><summary>Coordenadas · alternativa al dibujo</summary><p className="small-note">Un punto por línea: x,y entre 0 y 1.</p>
          <textarea aria-label="Coordenadas de la zona" value={coordinates} onChange={e=>setCoordinates(e.target.value)}/>
          <button type="button" className="button button-outline" onClick={()=>{
            const next=coordinates.split("\n").filter(Boolean).map(line=>line.split(",").map(Number));
            if(next.length>=3 && next.length<=32 && next.every(p=>p.length===2 && p.every(n=>Number.isFinite(n)&&n>=0&&n<=1))) {setPoints(next as [number,number][]);setError(null);}
            else setError("Escribe entre 3 y 32 puntos válidos, uno por línea.");
          }}>Aplicar coordenadas</button></details>
        <div className="button-row"><button type="button" className="button button-outline" disabled={!points.length||pending} onClick={()=>{const next=points.slice(0,-1);setPoints(next);setCoordinates(next.map(p=>p.join(",")).join("\n"));}}><Undo2 size={16}/>Deshacer</button>
          <button type="button" className="button button-dark" disabled={points.length<3||!name.trim()||pending} onClick={()=>void save()}><Save size={16}/>{pending?"Guardando…":"Guardar zona"}</button>
          {selected && <button type="button" className="button button-outline" disabled={pending} onClick={()=>void save(true)}><Trash2 size={16}/>Eliminar</button>}</div>
        {error&&<p className="error-box" role="alert">{error}</p>}<p role="status">{notice}</p>
      </div>
    </section>
    <section className="panel settings-panel"><div className="panel-heading"><h2>Guardadas</h2></div><div className="settings-body">
      {document.zones.length ? <ul className="settings-list">{document.zones.map(z=><li key={z.id}><button type="button" className="button button-outline w-full" onClick={()=>choose(z)}>{z.name}</button></li>)}</ul>:<p>Sin zonas</p>}
      <p className="small-note">La regla usa la ubicación de la cadera. Una zona no garantiza que la persona esté a salvo.</p>
    </div></section>
  </main>;
}
