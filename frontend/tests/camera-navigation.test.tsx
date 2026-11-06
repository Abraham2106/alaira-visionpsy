import {fireEvent,render,screen,waitFor} from "@testing-library/react";
import {beforeEach,expect,it,vi} from "vitest";
import App from "../src/App";

const capture=vi.hoisted(()=>({send:vi.fn(()=>true),ready:()=>true,clear:vi.fn(),refresh:vi.fn()}));
vi.mock("../src/hooks/useWebSocket",()=>({useWebSocket:()=>({connected:true,error:null,send:capture.send,canSend:capture.ready})}));
vi.mock("../src/hooks/useCameras",()=>({useCameras:()=>({cameras:[{id:"cam-1",name:"PC"},{id:"cam-2",name:"Celular"}],names:{"cam-1":"PC","cam-2":"Celular"},refresh:capture.refresh})}));
vi.mock("../src/hooks/useMonitor",()=>({useMonitor:()=>({views:{
  "cam-1":{frame:null,pose:null,status:{camera:"streaming",level:"ok",reasons:[]}},
  "cam-2":{frame:null,pose:null,status:{camera:"streaming",level:"ok",reasons:[]}},
},frame:null,pose:null,status:null,health:null,alerts:[],connected:true,error:null,updateAlert:capture.clear,clearFrame:capture.clear,clearError:capture.clear})}));

const stop=vi.fn();
const getUserMedia=vi.fn();
beforeEach(()=>{
  location.hash="#/camera";
  vi.clearAllMocks();
  vi.stubGlobal("isSecureContext",true);
  vi.stubGlobal("navigator",{mediaDevices:{getUserMedia}});
  vi.stubGlobal("fetch",vi.fn().mockImplementation(async(input)=>new Response(JSON.stringify(
    String(input).endsWith("/contacts")?[]:String(input).endsWith("/notifications")?{enabled:false,error:null,deliveries:[]}:{token:"test-only"}))));
  getUserMedia.mockResolvedValue({getTracks:()=>[{stop}],getVideoTracks:()=>[{addEventListener:vi.fn()}]});
  vi.spyOn(document,"hidden","get").mockReturnValue(false);
  vi.spyOn(HTMLMediaElement.prototype,"play").mockResolvedValue();
  vi.spyOn(HTMLVideoElement.prototype,"videoWidth","get").mockReturnValue(640);
  vi.spyOn(HTMLVideoElement.prototype,"videoHeight","get").mockReturnValue(480);
  vi.spyOn(HTMLCanvasElement.prototype,"getContext").mockReturnValue({drawImage:vi.fn()} as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype,"toBlob").mockImplementation(callback=>callback(new Blob(["jpeg"])));
});

it("conserva la webcam y sigue enviando al navegar; detener y salir liberan la cámara",async()=>{
  render(<App/>);
  fireEvent.click(await screen.findByRole("button",{name:"Iniciar cámara"}));
  await waitFor(()=>expect(capture.send).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("link",{name:"Monitor",exact:true}));
  expect(await screen.findByRole("figure",{name:"Cámara PC"})).toBeInTheDocument();
  expect(screen.getByRole("figure",{name:"Cámara Celular"})).toBeInTheDocument();
  const sent=capture.send.mock.calls.length;
  await waitFor(()=>expect(capture.send.mock.calls.length).toBeGreaterThan(sent));
  expect(stop).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("link",{name:"Conexiones",exact:true}));
  await screen.findByRole("heading",{name:"Conexiones",level:1});
  expect(stop).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("link",{name:"Cámara de PC",exact:true}));
  fireEvent.click(await screen.findByRole("button",{name:"Detener transmisión"}));
  expect(stop).toHaveBeenCalledTimes(1);
  expect(getUserMedia).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button",{name:"Iniciar cámara"}));
  await waitFor(()=>expect(getUserMedia).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole("button",{name:"Salir"}));
  expect(stop).toHaveBeenCalledTimes(2);
});
