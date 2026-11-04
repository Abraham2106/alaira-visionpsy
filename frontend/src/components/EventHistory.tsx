import { useEffect, useState } from "react";
import { api } from "../config";
import type { AlertMsg } from "../types";
import AlertPanel from "./AlertPanel";

export default function EventHistory({token}:{token:string}) {
  const [alerts,setAlerts]=useState<AlertMsg[]>([]);
  const [error,setError]=useState<string|null>(null);
  useEffect(()=>{
    let cancelled=false;
    api<AlertMsg[]>("/alerts",token).then(data=>{if(!cancelled)setAlerts(data);}).catch(()=>{if(!cancelled)setError("No se pudo cargar el historial.");});
    return ()=>{cancelled=true;};
  },[token]);
  return <main className="history-layout">{error&&<p className="error-box" role="alert">{error}</p>}
    <AlertPanel token={token} alerts={alerts} onUpdate={alert=>setAlerts(previous=>previous.map(a=>a.id===alert.id?alert:a))}/>
    <p className="small-note">Últimos eventos guardados en esta PC. La atención registrada y la recuperación observada son hechos distintos.</p>
  </main>;
}
