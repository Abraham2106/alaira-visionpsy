import {act,render} from "@testing-library/react";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {useCameraCapture} from "../src/hooks/useCameraCapture";
import {CAPTURE} from "../src/config";

const send=vi.fn(()=>true),onError=vi.fn(),stop=vi.fn();
const track={stop,addEventListener:vi.fn()};
const stream={getTracks:()=>[track],getVideoTracks:()=>[track]};
const getUserMedia=vi.fn();
const ready=vi.fn(()=>true);
function Capture({running=true}:{running?:boolean}) {
  const {videoRef,captureRef}=useCameraCapture("camera",running,send,onError,ready);
  return <><video ref={videoRef}/><canvas ref={captureRef}/></>;
}
beforeEach(()=>{
  vi.useFakeTimers();
  vi.clearAllMocks();
  ready.mockReturnValue(true);
  vi.stubGlobal("isSecureContext",true);
  vi.stubGlobal("navigator",{mediaDevices:{getUserMedia}});
  vi.spyOn(document,"hidden","get").mockReturnValue(false);
  vi.spyOn(HTMLMediaElement.prototype,"play").mockResolvedValue();
  vi.spyOn(HTMLVideoElement.prototype,"videoWidth","get").mockReturnValue(1920);
  vi.spyOn(HTMLVideoElement.prototype,"videoHeight","get").mockReturnValue(1080);
  vi.spyOn(HTMLCanvasElement.prototype,"getContext").mockReturnValue({drawImage:vi.fn()} as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype,"toBlob").mockImplementation(callback=>callback(new Blob(["jpeg"])));
  getUserMedia.mockResolvedValue(stream);
});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});

it("limita resolución y envíos; detener libera la cámara",async()=>{
  const view=render(<Capture/>);
  await act(async()=>{await vi.advanceTimersByTimeAsync(1000);});
  expect(getUserMedia).toHaveBeenCalledWith({video:{facingMode:{ideal:"environment"},width:{ideal:800},frameRate:{ideal:24,max:30}},audio:false});
  expect(send.mock.calls.length).toBeGreaterThanOrEqual(23);
  expect(send.mock.calls.length).toBeLessThanOrEqual(CAPTURE.fps);
  expect(view.container.querySelector("canvas")).toHaveProperty("width",800);
  expect(view.container.querySelector("canvas")).toHaveProperty("height",450);
  const sent=send.mock.calls.length;
  view.rerender(<Capture running={false}/>);
  expect(stop).toHaveBeenCalledOnce();
  await act(async()=>{await vi.advanceTimersByTimeAsync(1000);});
  expect(send).toHaveBeenCalledTimes(sent);
});

it("libera un permiso resuelto después de detener",async()=>{
  let grant!:(value:typeof stream)=>void;
  getUserMedia.mockReturnValue(new Promise(resolve=>{grant=resolve;}));
  const view=render(<Capture/>);
  view.rerender(<Capture running={false}/>);
  await act(async()=>{grant(stream);});
  expect(stop).toHaveBeenCalledOnce();
  expect(send).not.toHaveBeenCalled();
});

it("descarta una codificación tardía al ocultar y retoma sin cola",async()=>{
  let encoded:BlobCallback|undefined;
  vi.mocked(HTMLCanvasElement.prototype.toBlob).mockImplementation(callback=>{encoded=callback;});
  render(<Capture/>);
  await act(async()=>{await vi.advanceTimersByTimeAsync(200);});
  vi.spyOn(document,"hidden","get").mockReturnValue(true);
  act(()=>encoded?.(new Blob(["stale"])));
  await act(async()=>{await vi.advanceTimersByTimeAsync(2000);});
  expect(send).not.toHaveBeenCalled();
  vi.spyOn(document,"hidden","get").mockReturnValue(false);
  await act(async()=>{await vi.advanceTimersByTimeAsync(200);});
  act(()=>encoded?.(new Blob(["current"])));
  expect(send).toHaveBeenCalledOnce();
});

it("informa permiso denegado sin dejar temporizador enviando",async()=>{
  getUserMedia.mockRejectedValue(new DOMException("Denied","NotAllowedError"));
  render(<Capture/>);
  await act(async()=>{await vi.advanceTimersByTimeAsync(1000);});
  expect(onError).toHaveBeenCalledWith(expect.stringContaining("permiso"));
  expect(send).not.toHaveBeenCalled();
});

it("no codifica mientras la PC está ocupada y retoma en 8 ms sin acumular frames",async()=>{
  ready.mockReturnValue(false);
  render(<Capture/>);
  await act(async()=>{await vi.advanceTimersByTimeAsync(350);});
  expect(HTMLCanvasElement.prototype.toBlob).not.toHaveBeenCalled();
  expect(send).not.toHaveBeenCalled();
  ready.mockReturnValue(true);
  await act(async()=>{await vi.advanceTimersByTimeAsync(8);});
  expect(send).toHaveBeenCalledOnce();
  expect(HTMLCanvasElement.prototype.toBlob).toHaveBeenCalledOnce();
  expect(stop).not.toHaveBeenCalled();
});
