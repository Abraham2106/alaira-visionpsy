import { useState, type FormEvent } from "react";

export default function TelegramSetup({ token, enabled, username, onChange }:
  {token:string;enabled:boolean;username?:string;onChange:()=>Promise<void>}) {
  const [secret,setSecret]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const [message,setMessage]=useState("");
  async function configure(event?:FormEvent) {
    event?.preventDefault();
    setBusy(true);setError(null);setMessage("");
    try {
      const response=await fetch("/api/telegram",{method:event?"POST":"DELETE",
        headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},
        ...(event?{body:JSON.stringify({token:secret.trim()})}:{})});
      if(!response.ok) {
        const result=await response.json().catch(()=>null) as {detail?:unknown}|null;
        throw new Error(typeof result?.detail==="string"?result.detail:"No se pudo conectar con Telegram.");
      }
      setSecret("");
      await onChange();
      setMessage(event?"Bot conectado. Ya puedes vincular al familiar.":"Bot desconectado.");
    } catch(cause) {setError(cause instanceof Error?cause.message:"No se pudo configurar Telegram.");}
    finally {setBusy(false);}
  }
  return <form className="telegram-setup" onSubmit={event=>void configure(event)}>
    <div className="family-toolbar"><strong>{enabled?`Telegram conectado${username?` · @${username}`:""}`:"Conectar Telegram"}</strong></div>
    <p className="small-note">En <a href="https://t.me/BotFather" target="_blank" rel="noreferrer">BotFather</a>, envía <code>/newbot</code> y pega aquí el token que te entrega. Solo se guarda en esta PC.</p>
    <label htmlFor="telegram-token">Token de BotFather</label>
    <input id="telegram-token" type="password" value={secret} onChange={e=>setSecret(e.target.value)} autoComplete="off" spellCheck={false} maxLength={150} disabled={busy} placeholder={enabled?"Pega otro token para actualizar":"Pega el token del bot"}/>
    <button type="submit" className="button button-dark" disabled={busy||!secret.trim()}>{busy?"Conectando…":enabled?"Actualizar bot":"Conectar bot"}</button>
    {enabled&&<button type="button" className="button button-quiet" disabled={busy} onClick={()=>void configure()}>Desconectar bot</button>}
    {error&&<p className="error-box" role="alert">{error}</p>}
    {message&&<p className="small-note" role="status">{message}</p>}
  </form>;
}
