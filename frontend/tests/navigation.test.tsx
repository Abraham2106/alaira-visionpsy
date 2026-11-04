import {act,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {beforeEach,expect,it,vi} from "vitest";
import QRCode from "qrcode";
import App from "../src/App";

vi.mock("qrcode",()=>({default:{toDataURL:vi.fn().mockResolvedValue("data:image/png;base64,demo")}}));
vi.mock("../src/hooks/useMonitor",()=>({useMonitor:()=>({frame:null,pose:null,status:null,health:null,alerts:[],connected:true,error:null,updateAlert:vi.fn()})}));
vi.mock("../src/hooks/useWebSocket",()=>({useWebSocket:()=>({connected:false,error:null,send:()=>false})}));
vi.mock("../src/hooks/useCameraCapture",()=>({useCameraCapture:()=>({videoRef:{current:null},captureRef:{current:null},frames:0,resetFrames:vi.fn()})}));

beforeEach(()=>{
  location.hash="";
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,_init?:RequestInit)=>new Response(JSON.stringify(
    String(input).endsWith("/zones")?{revision:0,zones:[]}:
    String(input).endsWith("/notifications")?{enabled:false,error:null,deliveries:[]}:
    String(input).endsWith("/pairing/camera")?{code:"single-use-code",expires_at:2000000000}:[]))));
});

it("el cuidador llega a zonas, conexión e historial; el QR no expone su token",async()=>{
  render(<App/>);
  fireEvent.change(screen.getByLabelText("Token de acceso"),{target:{value:"admin-test-only"}});
  fireEvent.click(screen.getByRole("button",{name:"Entrar"}));
  expect(screen.getByRole("heading",{name:"Monitor de actividad",level:1})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link",{name:"Zonas"}));
  await screen.findByRole("heading",{name:"Zonas",level:1});
  expect(await screen.findByText("Sin zonas")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link",{name:"Conexiones"}));
  await screen.findByRole("heading",{name:"Conexiones",level:1});
  fireEvent.change(screen.getByLabelText("Dirección HTTPS de esta PC en la red"),{target:{value:"https://192.168.1.20:5175/#/phone"}});
  await waitFor(()=>expect(QRCode.toDataURL).toHaveBeenCalledWith("https://192.168.1.20:5175/#/phone",expect.any(Object)));
  fireEvent.click(screen.getByRole("button",{name:"Generar código de cámara"}));
  await screen.findByText("single-use-code");
  expect(JSON.stringify(vi.mocked(QRCode.toDataURL).mock.calls)).not.toContain("admin-test-only");
  fireEvent.click(screen.getByRole("link",{name:"Historial"}));
  await screen.findByRole("heading",{name:"Historial",level:1});
  expect(await screen.findByText("Sin alertas por ahora")).toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.every(([,init])=>(init?.headers as Record<string,string>).Authorization==="Bearer admin-test-only")).toBe(true);
  fireEvent.click(screen.getByRole("button",{name:"Salir"}));
  expect(screen.getByLabelText("Token de acceso")).toHaveValue("");
});

it("la ruta móvil abre sin token administrador",async()=>{
  await act(async()=>{location.hash="#/phone";});
  render(<App/>);
  expect(screen.getByRole("heading",{name:"Cámara del celular",level:1})).toBeInTheDocument();
  expect(screen.queryByLabelText("Token de acceso")).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"Iniciar cámara"})).toBeDisabled();
});
