import {act,renderHook,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {useWebSocket} from "../src/hooks/useWebSocket";
import {useMonitor} from "../src/hooks/useMonitor";
import {encodeFrame} from "../src/frames";

class Socket {
  static OPEN=1;
  static instances:Socket[]=[];
  readyState=0;bufferedAmount=0;binaryType="blob";
  sent:unknown[]=[];
  onopen:(()=>void)|null=null;
  onmessage:((event:MessageEvent)=>void)|null=null;
  onclose:((event:CloseEvent)=>void)|null=null;
  onerror:(()=>void)|null=null;
  constructor(public url:string){Socket.instances.push(this);}
  send(data:unknown){this.sent.push(data);}
  close(){this.readyState=3;this.onclose?.({code:1000,reason:""} as CloseEvent);}
  open(){this.readyState=1;this.onopen?.();}
  message(data:unknown){this.onmessage?.({data} as MessageEvent);}
}

beforeEach(()=>{
  Socket.instances=[];
  vi.stubGlobal("WebSocket",Socket);
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify({pose:"stub",vision:"stub",synthetic:true}))));
});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});

it("solo admite un frame hasta que el backend confirme procesamiento",()=>{
  const {result}=renderHook(()=>useWebSocket("/ws/ingest","token"));
  const socket=Socket.instances[0];
  act(()=>socket.open());
  expect(JSON.parse(socket.sent[0] as string)).toMatchObject({type:"auth",flow_control:true});
  const frame=new Blob(["frame"]);
  expect(result.current.send(frame)).toBe(true);
  expect(result.current.send(frame)).toBe(false);
  act(()=>socket.message(JSON.stringify({type:"processed"})));
  expect(result.current.send(frame)).toBe(true);
});

it("reconecta ante corte de transporte y deja de reintentar ante rechazo",async()=>{
  vi.useFakeTimers();
  renderHook(()=>useWebSocket("/ws/ingest","token"));
  act(()=>Socket.instances[0].open());
  act(()=>Socket.instances[0].close());
  await act(async()=>{await vi.advanceTimersByTimeAsync(1000);});
  expect(Socket.instances).toHaveLength(2);
  act(()=>Socket.instances[1].onclose?.({code:1008,reason:"revoked"} as CloseEvent));
  await act(async()=>{await vi.advanceTimersByTimeAsync(20000);});
  expect(Socket.instances).toHaveLength(2);
});

const packet=(camera:string,body:string)=>encodeFrame(camera,new TextEncoder().encode(body));
const poseMsg=(camera:string,timestamp:number)=>JSON.stringify({type:"pose",camera_id:camera,timestamp,landmarks:null});
const statusMsg=(camera:string,state:string,timestamp:number)=>JSON.stringify({type:"status",camera_id:camera,camera:state,reasons:[],level:"ok",timestamp,model_error:null});

it("no muestra una imagen nueva con la pose anterior y limpia al desconectar",async()=>{
  const {result}=renderHook(()=>useMonitor("token"));
  const socket=Socket.instances[0];
  act(()=>socket.open());
  await waitFor(()=>expect(result.current.connected).toBe(true));
  expect(socket.binaryType).toBe("arraybuffer");
  act(()=>socket.message(packet("cam-1","first")));
  expect(result.current.frame).toBeNull();
  act(()=>socket.message(poseMsg("cam-1",1)));
  expect(result.current.frame?.size).toBe(5);
  act(()=>socket.message(packet("cam-1","second!")));
  expect(result.current.frame?.size).toBe(5);
  act(()=>socket.message(poseMsg("cam-1",2)));
  expect(result.current.frame?.size).toBe(7);
  act(()=>socket.message(statusMsg("cam-1","disconnected",3)));
  expect(result.current.frame).toBeNull();
});

it("mantiene vistas independientes por cámara y expone la elegida",async()=>{
  const {result}=renderHook(()=>useMonitor("token",true,"cam-2"));
  const socket=Socket.instances[0];
  act(()=>socket.open());
  await waitFor(()=>expect(result.current.connected).toBe(true));
  act(()=>{
    socket.message(packet("cam-1","uno"));socket.message(poseMsg("cam-1",1));
    socket.message(packet("cam-2","dos!"));socket.message(poseMsg("cam-2",1));
  });
  expect(result.current.views["cam-1"].frame?.size).toBe(3);
  expect(result.current.views["cam-2"].frame?.size).toBe(4);
  expect(result.current.frame?.size).toBe(4);
  // Que una cámara se desconecte no borra la imagen de la otra.
  act(()=>socket.message(statusMsg("cam-2","disconnected",2)));
  expect(result.current.frame).toBeNull();
  expect(result.current.views["cam-1"].frame?.size).toBe(3);
});

it("rechaza un frame con prefijo inválido sin romper el monitor",async()=>{
  const {result}=renderHook(()=>useMonitor("token"));
  const socket=Socket.instances[0];
  act(()=>socket.open());
  await waitFor(()=>expect(result.current.connected).toBe(true));
  act(()=>socket.message(new Uint8Array([9,1,2]).buffer));
  expect(result.current.error).toMatch(/frame inválido/);
  act(()=>result.current.clearError());
  act(()=>socket.message(packet("cam-1","ok")));
  act(()=>socket.message(poseMsg("cam-1",1)));
  expect(result.current.frame?.size).toBe(2);
});

it("envía camera_id en la autenticación solo cuando se indica",()=>{
  renderHook(()=>useWebSocket("/ws/ingest","token",undefined,true,"cam-2"));
  renderHook(()=>useWebSocket("/ws/ingest","token"));
  act(()=>Socket.instances[0].open());
  act(()=>Socket.instances[1].open());
  expect(JSON.parse(Socket.instances[0].sent[0] as string)).toMatchObject({type:"auth",camera_id:"cam-2"});
  expect(JSON.parse(Socket.instances[1].sent[0] as string)).not.toHaveProperty("camera_id");
});
