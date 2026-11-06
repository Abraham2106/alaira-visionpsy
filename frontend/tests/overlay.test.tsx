import {act,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import VideoCanvas from "../src/components/VideoCanvas";
import type {PoseMsg} from "../src/types";

const context={drawImage:vi.fn(),beginPath:vi.fn(),moveTo:vi.fn(),lineTo:vi.fn(),stroke:vi.fn(),arc:vi.fn(),fill:vi.fn(),strokeStyle:"",fillStyle:"",lineWidth:0};
beforeEach(()=>{
  vi.clearAllMocks();
  vi.spyOn(HTMLCanvasElement.prototype,"getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
  vi.stubGlobal("createImageBitmap",vi.fn());
});
afterEach(()=>vi.unstubAllGlobals());

it("superpone la pose sin pintar un JPEG que tape el video directo",async()=>{
  const bitmap={width:800,height:600,close:vi.fn()};
  vi.mocked(createImageBitmap).mockResolvedValue(bitmap as unknown as ImageBitmap);
  const landmarks:[number,number,number][]=Array.from({length:33},()=>[.5,.5,1]);
  const view=render(<VideoCanvas frame={new Blob(["frame"])} pose={{type:"pose",camera_id:"cam-1",timestamp:1,landmarks}} overlay/>);
  await waitFor(()=>expect(bitmap.close).toHaveBeenCalledOnce());
  expect(context.drawImage).not.toHaveBeenCalled();
  expect(context.arc).toHaveBeenCalledTimes(33);
  expect(view.container.firstChild).toHaveClass("video-overlay");
});

it.each([[900,900],[1200,900],[1600,900]])("alinea las articulaciones con el frame original %i×%i",async(width,height)=>{
  const bitmap={width,height,close:vi.fn()};
  vi.mocked(createImageBitmap).mockResolvedValue(bitmap as unknown as ImageBitmap);
  const landmarks:[number,number,number][]=Array.from({length:33},()=>[.5,.5,0]);
  landmarks[11]=[.25,.25,1];landmarks[12]=[.75,.25,1];
  landmarks[23]=[.25,.75,1];landmarks[24]=[.75,.75,1];
  const pose:PoseMsg={type:"pose",timestamp:1,landmarks};
  render(<VideoCanvas frame={new Blob(["frame"])} pose={pose}/>);
  await waitFor(()=>expect(context.drawImage).toHaveBeenCalledOnce());
  const canvas=screen.getByLabelText("Último frame y esqueleto estimado");
  expect(canvas).toHaveProperty("width",width);
  expect(canvas).toHaveProperty("height",height);
  expect(context.moveTo).toHaveBeenCalledWith(width*.25,height*.25);
  expect(context.lineTo).toHaveBeenCalledWith(width*.75,height*.25);
  expect(context.arc).toHaveBeenCalledTimes(4);
  expect(bitmap.close).toHaveBeenCalledOnce();
});

it("descarta un bitmap antiguo que termina después del frame nuevo",async()=>{
  let finish!:(bitmap:ImageBitmap)=>void;
  const old={width:900,height:900,close:vi.fn()};
  const current={width:1600,height:900,close:vi.fn()};
  vi.mocked(createImageBitmap).mockReturnValueOnce(new Promise(resolve=>{finish=resolve;}));
  vi.mocked(createImageBitmap).mockResolvedValueOnce(current as unknown as ImageBitmap);
  const view=render(<VideoCanvas frame={new Blob(["old"])} pose={null}/>);
  view.rerender(<VideoCanvas frame={new Blob(["current"])} pose={null}/>);
  await waitFor(()=>expect(context.drawImage).toHaveBeenCalledOnce());
  await act(async()=>finish(old as unknown as ImageBitmap));
  expect(context.drawImage).toHaveBeenCalledOnce();
  expect(context.drawImage).toHaveBeenCalledWith(current,0,0);
  expect(old.close).toHaveBeenCalledOnce();
  expect(screen.getByLabelText("Último frame y esqueleto estimado")).toHaveProperty("width",1600);
  view.rerender(<VideoCanvas frame={null} pose={null}/>);
  expect(screen.queryByLabelText("Último frame y esqueleto estimado")).not.toBeInTheDocument();
});
