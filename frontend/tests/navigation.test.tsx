import {act,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {beforeEach,expect,it,vi} from "vitest";
import QRCode from "qrcode";
import App from "../src/App";
import {StrictMode} from "react";
import FamilySettings from "../src/components/FamilySettings";

vi.mock("qrcode",()=>({default:{toDataURL:vi.fn().mockResolvedValue("data:image/png;base64,demo")}}));
vi.mock("../src/hooks/useMonitor",()=>({useMonitor:()=>({views:{},frame:null,pose:null,status:null,health:null,alerts:[],connected:true,error:null,updateAlert:vi.fn()})}));
vi.mock("../src/hooks/useWebSocket",()=>({useWebSocket:()=>({connected:false,error:null,send:()=>false})}));
vi.mock("../src/hooks/useCameraCapture",()=>({useCameraCapture:()=>({videoRef:{current:null},captureRef:{current:null},frames:0,resetFrames:vi.fn()})}));

beforeEach(()=>{
  location.hash="";
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,_init?:RequestInit)=> String(input).endsWith("/local-session") ? new Response("{}",{status:403}) : new Response(JSON.stringify(
    String(input).endsWith("/zones")?{revision:0,zones:[]}:
    String(input).endsWith("/notifications")?{enabled:false,error:null,deliveries:[]}:
    String(input).endsWith("/pairing/camera")?{code:"single-use-code",expires_at:Date.now()/1000+300}:[]))));
});

it("el cuidador llega a zonas, conexión e historial; el QR no expone su token",async()=>{
  render(<App/>);
  fireEvent.change(await screen.findByLabelText("Token de acceso"),{target:{value:"admin-test-only"}});
  fireEvent.click(screen.getByRole("button",{name:"Entrar"}));
  await screen.findByRole("button",{name:"Salir"});
  expect(screen.getByRole("heading",{name:"Monitor de actividad",level:1})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link",{name:"Zonas"}));
  await screen.findByRole("heading",{name:"Zonas",level:1});
  expect(await screen.findByText("Sin zonas")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link",{name:"Conexiones"}));
  await screen.findByRole("heading",{name:"Conexiones",level:1});
  fireEvent.change(screen.getByLabelText("Dirección de cámara"),{target:{value:"https://192.168.1.20:5175/#/phone"}});
  expect(screen.queryByAltText("QR para vincular la cámara del celular")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"Generar QR de cámara"}));
  await screen.findByText("single-use-code");
  await waitFor(()=>expect(QRCode.toDataURL).toHaveBeenCalledWith("https://192.168.1.20:5175/#/phone?code=single-use-code",expect.any(Object)));
  expect(JSON.stringify(vi.mocked(QRCode.toDataURL).mock.calls)).not.toContain("admin-test-only");
  fireEvent.click(screen.getByRole("link",{name:"Historial"}));
  await screen.findByRole("heading",{name:"Historial",level:1});
  expect(await screen.findByText("Sin alertas por ahora")).toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.filter(([input])=>!String(input).endsWith("/local-session")).every(([,init])=>(init?.headers as Record<string,string>).Authorization==="Bearer admin-test-only")).toBe(true);
  fireEvent.click(screen.getByRole("button",{name:"Salir"}));
  expect(screen.getByLabelText("Token de acceso")).toHaveValue("");
});

it("la ruta móvil abre sin token administrador",async()=>{
  await act(async()=>{location.hash="#/phone";});
  render(<App/>);
  expect(screen.getByRole("heading",{name:"Cámara del celular",level:1})).toBeInTheDocument();
  expect(screen.queryByLabelText("Token de acceso")).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"Iniciar cámara"})).toBeDisabled();
  expect(fetch).not.toHaveBeenCalled();
});

it("entra automáticamente en esta PC sin pedir ni guardar el token",async()=>{
  const fallback = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=> String(input).endsWith("/local-session")
    ? new Response(JSON.stringify({token:"local-memory-only"})) : fallback(input,init));
  render(<App/>);
  expect(await screen.findByRole("button",{name:"Salir"})).toBeInTheDocument();
  expect(screen.queryByLabelText("Token de acceso")).not.toBeInTheDocument();
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
});

it("no inicia sesión con un token manual rechazado por el backend",async()=>{
  const fallback = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=> String(input).endsWith("/health")
    ? new Response("{}",{status:401}) : fallback(input,init));
  render(<App/>);
  fireEvent.change(await screen.findByLabelText("Token de acceso"),{target:{value:"wrong"}});
  fireEvent.click(screen.getByRole("button",{name:"Entrar"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Token de acceso inválido");
  expect(screen.queryByRole("button",{name:"Salir"})).not.toBeInTheDocument();
});

it("el QR abre la ruta móvil y se canjea una sola vez, sin activar la cámara",async()=>{
  location.hash="#/phone?code=single-use-qr";
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({token:"camera-only",camera_id:"cam-2"})));
  render(<StrictMode><App/></StrictMode>);
  expect(await screen.findByText("Vinculada como cam-2.")).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledWith("/api/camera/pair",expect.objectContaining({method:"POST",body:JSON.stringify({code:"single-use-qr"})}));
  expect(location.hash).toBe("#/phone");
  expect(screen.queryByLabelText("Código de cámara")).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"Iniciar cámara"})).toBeDisabled();
});

it("un QR vencido permite volver a vincular y no inicia captura",async()=>{
  location.hash="#/phone?code=expired-qr";
  vi.mocked(fetch).mockResolvedValue(new Response("{}",{status:403}));
  render(<App/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("Genera uno nuevo en la PC");
  expect(location.hash).toBe("#/phone");
  expect(screen.getByRole("button",{name:"Iniciar cámara"})).toBeDisabled();
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({token:"camera-only",camera_id:"cam-2"})));
  await act(async()=>{location.hash="#/phone?code=replacement-qr";window.dispatchEvent(new HashChangeEvent("hashchange"));});
  expect(await screen.findByText("Vinculada como cam-2.")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("cada generación cambia el QR y solo incluye el código temporal",async()=>{
  let number=0;
  const fallback=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>String(input).includes("/pairing/camera")
    ? new Response(JSON.stringify({code:`code-${++number}`,expires_at:Date.now()/1000+300})) : fallback(input,init));
  render(<FamilySettings token="private-admin"/>);
  fireEvent.change(screen.getByLabelText("Dirección de cámara"),{target:{value:"https://192.168.1.20:5175/#/phone"}});
  fireEvent.click(screen.getByRole("button",{name:"Generar QR de cámara"}));
  await waitFor(()=>expect(QRCode.toDataURL).toHaveBeenCalledWith("https://192.168.1.20:5175/#/phone?code=code-1",expect.any(Object)));
  fireEvent.click(screen.getByRole("button",{name:"Generar nuevo QR"}));
  await waitFor(()=>expect(QRCode.toDataURL).toHaveBeenCalledWith("https://192.168.1.20:5175/#/phone?code=code-2",expect.any(Object)));
  expect(JSON.stringify(vi.mocked(QRCode.toDataURL).mock.calls)).not.toContain("private-admin");
});
