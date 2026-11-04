import {act,renderHook,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {useWebSocket} from "../src/hooks/useWebSocket";
import {useMonitor} from "../src/hooks/useMonitor";

class Socket {
  static OPEN=1;
  static instances:Socket[]=[];
  readyState=0;bufferedAmount=0;
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

it("no muestra una imagen nueva con la pose anterior y limpia al desconectar",async()=>{
  const {result}=renderHook(()=>useMonitor("token"));
  const socket=Socket.instances[0];
  act(()=>socket.open());
  await waitFor(()=>expect(result.current.connected).toBe(true));
  const first=new Blob(["first"]),second=new Blob(["second"]);
  act(()=>socket.message(first));
  expect(result.current.frame).toBeNull();
  act(()=>socket.message(JSON.stringify({type:"pose",timestamp:1,landmarks:null})));
  expect(result.current.frame).toBe(first);
  act(()=>socket.message(second));
  expect(result.current.frame).toBe(first);
  act(()=>socket.message(JSON.stringify({type:"pose",timestamp:2,landmarks:null})));
  expect(result.current.frame).toBe(second);
  act(()=>socket.message(JSON.stringify({type:"status",camera:"disconnected",reasons:["camera_disconnected"],level:"ok",timestamp:3,model_error:null})));
  expect(result.current.frame).toBeNull();
});
