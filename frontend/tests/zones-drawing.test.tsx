import {fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import ZoneEditor from "../src/components/ZoneEditor";

const NativeURL=URL;
vi.mock("../src/hooks/useMonitor",()=>({useMonitor:()=>({frame:new Blob(["reference"]),connected:true})}));
beforeEach(()=>{
  vi.stubGlobal("PointerEvent",MouseEvent);
  vi.stubGlobal("URL",class extends NativeURL {
    static createObjectURL=vi.fn(()=>"blob:reference");
    static revokeObjectURL=vi.fn();
  });
  vi.stubGlobal("fetch",vi.fn(async(_input:RequestInfo|URL,init?:RequestInit)=>{
    if(init?.method==="PUT"){
      const body=JSON.parse(init.body as string);
      return new Response(JSON.stringify({...body,revision:body.revision+1}));
    }
    return new Response(JSON.stringify({revision:0,zones:[]}));
  }));
});
afterEach(()=>vi.unstubAllGlobals());

it("dibuja sobre la imagen sin incluir bandas y mantiene el polígono al redimensionar",async()=>{
  const view=render(<ZoneEditor token="drawing-test"/>);
  await screen.findByText("Sin zonas");
  const image=await screen.findByAltText("Imagen de referencia para delimitar zonas");
  Object.defineProperty(image,"naturalWidth",{value:1600});
  Object.defineProperty(image,"naturalHeight",{value:900});
  fireEvent.load(image);
  const stage=screen.getByRole("img",{name:"Editor de polígono"});
  const bounds=vi.spyOn(stage,"getBoundingClientRect").mockReturnValue(new DOMRect(0,0,400,400));
  // Banda superior: no se añade un vértice.
  fireEvent.pointerDown(stage,{clientX:200,clientY:20});
  expect(stage.querySelectorAll("circle")).toHaveLength(0);
  fireEvent.pointerDown(stage,{clientX:100,clientY:143.75});
  fireEvent.pointerDown(stage,{clientX:300,clientY:143.75});
  fireEvent.pointerDown(stage,{clientX:300,clientY:256.25});
  expect(stage.querySelectorAll("circle")).toHaveLength(3);
  expect(stage.querySelector("polyline")).toHaveAttribute("points","400,225 1200,225 1200,675");
  // El nuevo punto a mitad de tamaño usa la misma referencia normalizada.
  bounds.mockReturnValue(new DOMRect(0,0,200,200));
  fireEvent.pointerDown(stage,{clientX:50,clientY:128.125});
  fireEvent.click(screen.getByRole("button",{name:"Guardar zona"}));
  await screen.findByText("Zonas guardadas");
  const saved=vi.mocked(fetch).mock.calls.find(([,init])=>init?.method==="PUT")!;
  expect(JSON.parse(saved[1]!.body as string).zones[0].polygon).toEqual([[.25,.25],[.75,.25],[.75,.75],[.25,.75]]);
  await waitFor(()=>expect(stage.querySelector("polygon")).toBeInTheDocument());
  view.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:reference");
});
