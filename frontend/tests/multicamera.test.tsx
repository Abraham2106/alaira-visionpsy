// Multicámara: paquete binario, estado agregado, mosaico del monitor y gestión de cámaras.
import {beforeEach,expect,it,vi} from "vitest";
import {fireEvent,render,screen,waitFor} from "@testing-library/react";
import App from "../src/App";
import ZoneEditor from "../src/components/ZoneEditor";
import FamilySettings from "../src/components/FamilySettings";
import {decodeFrame,encodeFrame} from "../src/frames";
import {sourceLabel,worstStatus} from "../src/monitorStatus";
import type {AlertMsg,StatusMsg} from "../src/types";

const monitor=vi.hoisted(()=>({state:{} as Record<string,unknown>}));
vi.mock("../src/hooks/useMonitor",()=>({useMonitor:()=>monitor.state}));
vi.mock("../src/hooks/useWebSocket",()=>({useWebSocket:()=>({connected:false,error:null,send:()=>false})}));
vi.mock("qrcode",()=>({default:{toDataURL:vi.fn().mockResolvedValue("data:image/png;base64,demo")}}));

const status=(camera_id:string,level:StatusMsg["level"],camera:StatusMsg["camera"]="streaming"):StatusMsg=>
  ({type:"status",camera_id,timestamp:1,level,reasons:[],camera,model_error:null});
const CAMERAS=[{id:"cam-1",name:"Sala",state:"streaming",connected:true},{id:"cam-2",name:"Pasillo",state:"streaming",connected:true}];
const fall:AlertMsg={type:"alert",id:"shared",timestamp:100,updated_at:100,level:"critical",reasons:["immobile"],state:"OPEN",event:null,
  vision:null,vision_error:null,attention:"pending",recovery_at:null,kind:"fall",sources:["cam-1","cam-2"],zones:null};

beforeEach(()=>{
  location.hash="";
  monitor.state={views:{},frame:null,pose:null,status:null,health:null,alerts:[],connected:true,error:null,updateAlert:vi.fn(),clearFrame:vi.fn(),clearError:vi.fn()};
  vi.stubGlobal("fetch",vi.fn());
});

it("codifica y decodifica el paquete [longitud][camera_id][JPEG]",()=>{
  const jpeg=new Uint8Array([0xff,0xd8,0xff,0xd9]);
  const packet=decodeFrame(encodeFrame("cam-2",jpeg))!;
  expect(packet.cameraId).toBe("cam-2");
  expect(packet.jpeg.size).toBe(4);
  expect(packet.jpeg.type).toBe("image/jpeg");
  expect(decodeFrame(encodeFrame("cámara-ñ",jpeg))!.cameraId).toBe("cámara-ñ");
});

it("descarta paquetes sin camera_id, truncados o con UTF-8 inválido",()=>{
  expect(decodeFrame(new Uint8Array([0,1,2,3]).buffer)).toBeNull();      // longitud 0
  expect(decodeFrame(new Uint8Array([5,99,97,109]).buffer)).toBeNull();  // más corto que su prefijo
  expect(decodeFrame(new Uint8Array([3,99,97,109]).buffer)).toBeNull();  // prefijo completo pero sin JPEG
  expect(decodeFrame(new Uint8Array([2,0xff,0xfe,1,2]).buffer)).toBeNull(); // UTF-8 inválido
  expect(decodeFrame(new ArrayBuffer(0))).toBeNull();
});

it("worstStatus elige la cámara en directo más grave y cae a la preferida si ninguna transmite",()=>{
  expect(worstStatus({"cam-1":status("cam-1","ok"),"cam-2":status("cam-2","critical")},"cam-1")?.camera_id).toBe("cam-2");
  expect(worstStatus({"cam-1":status("cam-1","suspect"),"cam-2":status("cam-2","ok")},"cam-2")?.camera_id).toBe("cam-1");
  // Una cámara caída no oculta el estado de la que sigue transmitiendo.
  expect(worstStatus({"cam-1":status("cam-1","ok"),"cam-2":status("cam-2","critical","disconnected")},"cam-2")?.camera_id).toBe("cam-1");
  expect(worstStatus({"cam-1":status("cam-1","ok","waiting"),"cam-2":null},"cam-1")?.camera_id).toBe("cam-1");
  expect(worstStatus({"cam-1":null},"cam-1")).toBeNull();
});

it("sourceLabel nombra las cámaras solo cuando hay varias en la habitación",()=>{
  expect(sourceLabel(fall,{"cam-1":"Sala","cam-2":"Pasillo"})).toBe("Sala + Pasillo");
  expect(sourceLabel(fall,{"cam-1":"Sala"})).toBe("");
  expect(sourceLabel(fall,undefined)).toBe("");
  expect(sourceLabel({...fall,sources:["cam-3"]},{"cam-1":"Sala","cam-2":"Pasillo"})).toBe("cam-3");
});

it("el monitor muestra un mosaico con una baldosa por cámara y la alerta compartida",async()=>{
  vi.mocked(fetch).mockImplementation(async()=>new Response(JSON.stringify(CAMERAS)));
  monitor.state={...monitor.state,alerts:[fall],views:{
    "cam-1":{frame:null,pose:null,status:status("cam-1","ok")},
    "cam-2":{frame:null,pose:null,status:status("cam-2","critical")},
  }};
  render(<App/>);
  fireEvent.change(await screen.findByLabelText("Token de acceso"),{target:{value:"admin-test-only"}});
  fireEvent.click(screen.getByRole("button",{name:"Entrar"}));
  const hall=await screen.findByRole("figure",{name:"Cámara Pasillo"});
  expect(screen.getByRole("figure",{name:"Cámara Sala"})).not.toHaveClass("mosaic-tile-alert");
  expect(hall).toHaveClass("mosaic-tile-alert");
  expect(screen.getByText("2/2 en directo")).toBeInTheDocument();
  expect(screen.getByRole("heading",{name:"Cámaras",level:2})).toBeInTheDocument();
  expect(screen.getByText("Detectada por: Sala + Pasillo")).toBeInTheDocument();
  expect(screen.getAllByText(/Sala \+ Pasillo/).length).toBeGreaterThanOrEqual(2); // banner + panel
});

it("con una sola cámara el monitor conserva la vista única",async()=>{
  vi.mocked(fetch).mockImplementation(async()=>new Response(JSON.stringify([CAMERAS[0]])));
  monitor.state={...monitor.state,views:{"cam-1":{frame:null,pose:null,status:status("cam-1","ok")}}};
  render(<App/>);
  fireEvent.change(await screen.findByLabelText("Token de acceso"),{target:{value:"admin-test-only"}});
  fireEvent.click(screen.getByRole("button",{name:"Entrar"}));
  expect(await screen.findByText("En directo")).toBeInTheDocument();
  expect(screen.queryByRole("figure")).not.toBeInTheDocument();
  expect(screen.getByRole("heading",{name:"Cámara",level:2})).toBeInTheDocument();
});

it("genera el código de una cámara concreta, agrega y quita cámaras",async()=>{
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const url=String(input);
    const body=url.includes("/cameras")?(init?.method==="POST"?{id:"cam-3",name:"Cocina",state:"waiting",connected:false}:CAMERAS)
      :url.includes("/contacts")?[]:url.includes("/notifications")?{enabled:false,error:null,deliveries:[]}:{code:"once-2",expires_at:Date.now()/1000+300};
    return new Response(JSON.stringify(body));
  });
  const calls=()=>vi.mocked(fetch).mock.calls.map(([url,init])=>`${init?.method??"GET"} ${String(url)}`);
  render(<FamilySettings token="test-token"/>);
  fireEvent.change(await screen.findByLabelText("Cámara a vincular"),{target:{value:"cam-2"}});
  fireEvent.click(screen.getByRole("button",{name:"Generar QR de cámara"}));
  await screen.findByText("once-2");
  expect(calls().some(call=>call.startsWith("POST")&&call.includes("/pairing/camera?camera_id=cam-2"))).toBe(true);
  fireEvent.click(screen.getByRole("button",{name:"Desvincular cámara"}));
  await waitFor(()=>expect(calls().some(call=>call.startsWith("DELETE")&&call.includes("/camera/pair?camera_id=cam-2"))).toBe(true));
  expect(screen.queryByText("once-2")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Nombre de la nueva cámara"),{target:{value:" Cocina "}});
  fireEvent.click(screen.getByRole("button",{name:"Agregar cámara"}));
  await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(([url,init])=>String(url).endsWith("/cameras")&&init?.method==="POST"
    &&JSON.parse(init.body as string).name==="Cocina")).toBe(true));
  // cam-1 es la cámara principal y no se puede quitar.
  const remove=screen.getAllByRole("button",{name:"Quitar cámara"});
  expect(remove).toHaveLength(1);
  fireEvent.click(remove[0]);
  await waitFor(()=>expect(calls().some(call=>call.startsWith("DELETE")&&call.endsWith("/cameras/cam-2"))).toBe(true));
});

it("el editor de zonas carga y guarda las zonas de la cámara elegida",async()=>{
  const polygon=[[.1,.1],[.8,.1],[.8,.8]];
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const url=String(input);
    if(url.includes("/cameras"))return new Response(JSON.stringify(CAMERAS));
    if(init?.method==="PUT")return new Response(JSON.stringify({revision:8,zones:[]}));
    return new Response(JSON.stringify(url.includes("camera_id=cam-2")?{revision:7,zones:[{id:"hall",name:"Cama pasillo",kind:"bed",polygon}]}:{revision:0,zones:[]}));
  });
  render(<ZoneEditor token="test-token"/>);
  await screen.findByText("Sin zonas");
  fireEvent.change(await screen.findByLabelText("Cámara"),{target:{value:"cam-2"}});
  fireEvent.click(await screen.findByRole("button",{name:"Cama pasillo"}));
  fireEvent.click(screen.getByRole("button",{name:"Eliminar"}));
  await screen.findByText("Zonas guardadas");
  const put=vi.mocked(fetch).mock.calls.find(([,init])=>init?.method==="PUT")!;
  expect(String(put[0])).toContain("/zones?camera_id=cam-2");
  expect(JSON.parse(put[1]!.body as string)).toEqual({revision:7,zones:[]});
  // cam-1 conserva la ruta histórica sin parámetro.
  expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).endsWith("/zones"))).toBe(true);
});

it("conserva cada QR al cambiar de cámara y selecciona la recién agregada",async()=>{
  const cameras=[...CAMERAS];
  let codeNumber=0;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const url=String(input);
    let body:unknown=[];
    if(url.endsWith("/cameras")) {
      if(init?.method==="POST") {
        const created={id:"cam-3",name:"Cocina",state:"waiting",connected:false};
        cameras.push(created);body=created;
      } else body=cameras;
    } else if(url.includes("/pairing/camera")) body={code:`isolated-${++codeNumber}`,expires_at:Date.now()/1000+300};
    else if(url.includes("/notifications")) body={enabled:false,error:null,deliveries:[]};
    return new Response(JSON.stringify(body));
  });
  render(<FamilySettings token="test-token"/>);
  const selected=await screen.findByLabelText("Cámara a vincular");
  fireEvent.click(screen.getByRole("button",{name:"Generar QR de cámara"}));
  await screen.findByText("isolated-1");
  fireEvent.change(selected,{target:{value:"cam-2"}});
  fireEvent.click(screen.getByRole("button",{name:"Generar QR de cámara"}));
  await screen.findByText("isolated-2");
  fireEvent.change(selected,{target:{value:"cam-1"}});
  expect(await screen.findByText("isolated-1")).toBeInTheDocument();
  expect(codeNumber).toBe(2); // Seleccionar no genera códigos ni renueva credenciales.
  fireEvent.change(screen.getByLabelText("Nombre de la nueva cámara"),{target:{value:"Cocina"}});
  fireEvent.click(screen.getByRole("button",{name:"Agregar cámara"}));
  await waitFor(()=>expect(selected).toHaveValue("cam-3"));
  fireEvent.click(screen.getByRole("button",{name:"Generar QR de cámara"}));
  await screen.findByText("isolated-3");
  expect(vi.mocked(fetch).mock.calls.some(([url,init])=>String(url).endsWith("/pairing/camera?camera_id=cam-3")&&init?.method==="POST")).toBe(true);
  fireEvent.change(selected,{target:{value:"cam-1"}});
  expect(await screen.findByText("isolated-1")).toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.some(([,init])=>init?.method==="DELETE")).toBe(false);
  fireEvent.click(screen.getByRole("button",{name:"Desvincular cámara"}));
  await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(([url,init])=>String(url)==="/api/camera/pair?camera_id=cam-1"&&init?.method==="DELETE")).toBe(true));
});
