import {beforeEach,expect,it,vi} from "vitest";
import {fireEvent,render,screen,waitFor} from "@testing-library/react";
import ZoneEditor from "../src/components/ZoneEditor";
import AlertPanel from "../src/components/AlertPanel";
import AlertBanner from "../src/components/AlertBanner";
import MobileCamera from "../src/components/MobileCamera";
import FamilySettings from "../src/components/FamilySettings";
import type {AlertMsg} from "../src/types";

vi.mock("../src/hooks/useMonitor",()=>({useMonitor:()=>({frame:null,connected:true})}));
vi.mock("../src/hooks/useWebSocket",()=>({useWebSocket:()=>({connected:false,error:null,send:()=>false})}));
vi.mock("../src/hooks/useCameraCapture",()=>({useCameraCapture:()=>({videoRef:{current:null},captureRef:{current:null},frames:0,resetFrames:()=>{}})}));
beforeEach(()=>{vi.stubGlobal("fetch",vi.fn());});

it("vincula un respaldo con un código de alcance propio",async()=>{
  vi.mocked(fetch).mockImplementation(async(input)=>new Response(JSON.stringify(
    String(input).includes("/contacts") ? [{chat_id:"2",alias:"Familiar",role:"backup",active:1}]:
    String(input).includes("/notifications") ? {enabled:false,error:null,deliveries:[]}:
    {code:"backup-once",expires_at:200})));
  render(<FamilySettings token="test-token"/>);
  await screen.findByText("Familiar · Respaldo");
  fireEvent.change(screen.getByLabelText("Recibir avisos como"),{target:{value:"backup"}});
  fireEvent.click(screen.getByRole("button",{name:"Vincular familiar"}));
  await screen.findByText("/start backup-once");
  expect(vi.mocked(fetch).mock.calls.some(([url,init])=>String(url).includes("/pairing/telegram_backup")&&init?.method==="POST")).toBe(true);
});

// Las pantallas consultan /cameras además de /zones: el mock enruta por URL en vez de por orden.
function zonesApi(loaded:unknown,saved:unknown) {
  vi.mocked(fetch).mockImplementation(async(input,init)=>new Response(JSON.stringify(
    String(input).includes("/cameras")?[]:init?.method==="PUT"?saved:loaded)));
}

it("guarda una zona con coordenadas normalizadas y revisión",async()=>{
  const request=vi.mocked(fetch);
  zonesApi({revision:0,zones:[]},{revision:1,zones:[{id:"bed",name:"Cama",kind:"bed",polygon:[[.1,.1],[.8,.1],[.8,.8]]}]});
  render(<ZoneEditor token="test-token"/>);
  await screen.findByText("Sin zonas");
  fireEvent.change(screen.getByLabelText("Coordenadas de la zona"),{target:{value:"0.1,0.1\n0.8,0.1\n0.8,0.8"}});
  fireEvent.click(screen.getByRole("button",{name:"Aplicar coordenadas"}));
  fireEvent.click(screen.getByRole("button",{name:"Guardar zona"}));
  await screen.findByText("Zonas guardadas");
  const call=request.mock.calls.find(([,init])=>init?.method==="PUT");
  expect(call).toBeDefined();
  const body=JSON.parse(call![1]!.body as string);
  expect(body.revision).toBe(0);
  expect(body.zones[0].polygon).toEqual([[.1,.1],[.8,.1],[.8,.8]]);
});

it("edita, deshace y elimina una zona guardada sin reutilizar coordenadas viejas",async()=>{
  const polygon=[[.1,.1],[.8,.1],[.8,.8],[.1,.8]];
  zonesApi({revision:4,zones:[{id:"bed",name:"Cama guardada",kind:"bed",polygon}]},{revision:5,zones:[]});
  render(<ZoneEditor token="test-token"/>);
  fireEvent.click(await screen.findByRole("button",{name:"Cama guardada"}));
  expect(screen.getByLabelText("Coordenadas de la zona")).toHaveValue("0.1,0.1\n0.8,0.1\n0.8,0.8\n0.1,0.8");
  fireEvent.click(screen.getByRole("button",{name:"Deshacer"}));
  expect(screen.getByLabelText("Coordenadas de la zona")).toHaveValue("0.1,0.1\n0.8,0.1\n0.8,0.8");
  expect(screen.getByRole("button",{name:"Guardar zona"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button",{name:"Eliminar"}));
  await screen.findByText("Zonas guardadas");
  const call=vi.mocked(fetch).mock.calls.find(([,init])=>init?.method==="PUT");
  expect(JSON.parse(call![1]!.body as string)).toEqual({revision:4,zones:[]});
  expect(screen.getByLabelText("Coordenadas de la zona")).toHaveValue("");
  expect(screen.getByRole("button",{name:"Guardar zona"})).toBeDisabled();
});

const alert:AlertMsg={type:"alert",id:"synthetic-event",timestamp:100,updated_at:100,level:"critical",reasons:["immobile"],state:"RESOLVED",event:"expire",vision:null,vision_error:null,attention:"expired",recovery_at:null,kind:"fall",sources:["cam-1"],zones:null};

it("prioriza la caída pendiente frente a la interrupción técnica sin cambiar el historial",()=>{
  const technical:AlertMsg={...alert,id:"camera",timestamp:200,state:"OPEN",kind:"technical",level:"suspect",reasons:["camera_disconnected"]};
  const fall:AlertMsg={...alert,id:"fall",state:"OPEN",attention:"pending"};
  const events=[technical,fall];
  const view=render(<AlertBanner alerts={events}/>);
  expect(screen.getByText("Posible caída detectada")).toBeInTheDocument();
  expect(events.map(e=>e.id)).toEqual(["camera","fall"]);
  view.rerender(<AlertBanner alerts={[technical,{...fall,state:"ACKNOWLEDGED"}]}/>);
  expect(screen.getByText("Monitoreo interrumpido")).toBeInTheDocument();
  view.rerender(<AlertBanner alerts={[alert]}/>);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("no presenta expiración como atención y registra una acción",async()=>{
  vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({...alert,attention:"attending"})));
  const onUpdate=vi.fn();
  render(<AlertPanel token="test-token" alerts={[alert]} onUpdate={onUpdate}/>);
  expect(screen.getByText("Expirada sin atención confirmada")).toBeInTheDocument();
  expect(screen.getByRole("button",{name:"Descartar"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"Estoy atendiendo"}));
  await waitFor(()=>expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({attention:"attending"})));
});

it("la cámara móvil no inicia sin vínculo y consentimiento",async()=>{
  vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({token:"ingest-only"})));
  render(<MobileCamera/>);
  expect(screen.getByRole("button",{name:"Iniciar cámara"})).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Código de cámara"),{target:{value:"temporary-code"}});
  fireEvent.click(screen.getByRole("button",{name:"Vincular"}));
  await screen.findByRole("button",{name:"Cambiar vinculación"});
  expect(screen.getByRole("button",{name:"Iniciar cámara"})).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("button",{name:"Iniciar cámara"})).toBeEnabled();
});
