import {useEffect,useRef,useState,type FormEvent,type ChangeEvent} from "react";

interface Picture {data:string;width:number;height:number;bytes:number;name:string}
interface Reply {id:string;question:string;answer:string;seconds:number;model:string;synthetic:boolean;image:string;width:number;height:number;bytes:number}

export default function VisionChat({token}:{token:string}) {
  const [picture,setPicture]=useState<Picture|null>(null);
  const [question,setQuestion]=useState("What position is the person in: standing, sitting, or something else?");
  const [replies,setReplies]=useState<Reply[]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const abort=useRef<AbortController|null>(null);
  useEffect(()=>()=>abort.current?.abort(),[]);
  async function choose(event:ChangeEvent<HTMLInputElement>) {
    const file=event.target.files?.[0];if(!file)return;
    setError("");setBusy(true);
    try {
      if(!["image/png","image/jpeg","image/webp"].includes(file.type)||file.size>10_000_000)throw new Error("Elige una foto PNG, JPEG o WebP de hasta 10 MB.");
      const bitmap=await createImageBitmap(file);
      try {
        if(bitmap.width*bitmap.height>40_000_000)throw new Error("La imagen supera los 40 megapíxeles.");
        const canvas=document.createElement("canvas");canvas.width=bitmap.width;canvas.height=bitmap.height;
        const context=canvas.getContext("2d");if(!context)throw new Error("No se pudo preparar la foto.");
        context.drawImage(bitmap,0,0);
        const data=canvas.toDataURL("image/jpeg",.85);
        const bytes=Math.floor(data.slice(data.indexOf(",")+1).length*3/4);
        if(bytes>2_000_000)throw new Error("El JPEG supera 2 MB. Reduce la foto antes de enviarla.");
        setPicture({data,width:bitmap.width,height:bitmap.height,bytes,name:file.name});
      } finally {bitmap.close();}
    } catch(cause){setError(cause instanceof Error?cause.message:"No se pudo abrir la foto.");}
    finally {setBusy(false);event.target.value="";}
  }
  async function send(event:FormEvent) {
    event.preventDefault();if(!picture||!question.trim()||busy)return;
    const selected=picture,prompt=question.trim();
    const controller=new AbortController();abort.current=controller;
    setBusy(true);setError("");
    try {
      const response=await fetch("/api/vision/ask",{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},signal:controller.signal,body:JSON.stringify({image:selected.data.slice(selected.data.indexOf(",")+1),question:prompt})});
      if(!response.ok) {
        const failure=await response.json().catch(()=>null);
        throw new Error(typeof failure?.detail==="string"?failure.detail:"No se pudo consultar el modelo.");
      }
      const result=await response.json();
      setReplies(previous=>[...previous,{...result,id:crypto.randomUUID(),question:prompt,image:selected.name,width:selected.width,height:selected.height,bytes:selected.bytes}].slice(-20));
    } catch(cause){if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:"No se pudo consultar el modelo.");}
    finally {setBusy(false);}
  }
  return <main className="vision-lab">
    <section className="panel vision-lab-input"><h2>Foto</h2>
      <label className="field-label" htmlFor="vision-photo">Cargar imagen</label>
      <input id="vision-photo" type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={event=>void choose(event)}/>
      {picture?<><img src={picture.data} alt="Foto seleccionada para el modelo"/><p className="small-note">{picture.name} · {picture.width} × {picture.height} · JPEG {Math.round(picture.bytes/1024)} KB</p></>:<p className="small-note">Elige una foto para empezar.</p>}
      <form onSubmit={event=>void send(event)}><label className="field-label" htmlFor="vision-question">Pregunta</label>
        <textarea id="vision-question" rows={4} maxLength={2000} value={question} onChange={event=>setQuestion(event.target.value)} disabled={busy}/>
        <button className="button button-dark w-full" type="submit" disabled={busy||!picture||!question.trim()}>{busy?"Procesando…":"Enviar al modelo"}</button>
      </form>
      <p className="small-note">Una foto por consulta, sin historial enviado al modelo. No genera alertas ni guarda fotos en disco.</p>
      {error&&<p role="alert" className="error-box">{error}</p>}
    </section>
    <section className="panel vision-lab-results"><div className="panel-heading"><h2>Respuestas</h2><button type="button" className="button button-quiet" disabled={busy||!replies.length} onClick={()=>setReplies([])}>Limpiar</button></div>
      <div className="vision-chat-log" role="log" aria-label="Respuestas del modelo">{!replies.length&&<p className="small-note">Aquí aparecerá la respuesta exacta de VisionPsy.</p>}{replies.map(reply=><article key={reply.id}>
        <p className="vision-chat-prompt">{reply.question}</p><p className="vision-chat-answer">{reply.answer}</p>
        <p className="small-note">{reply.synthetic?"SIMULADO":"VisionPsy local"} · {reply.seconds} s · {reply.image}</p>
      </article>)}</div>
      <details className="vision-chat-trace"><summary>Logs</summary><pre>{JSON.stringify(replies,null,2)}</pre></details>
    </section>
  </main>;
}
