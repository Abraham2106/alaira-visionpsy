import {act,render} from "@testing-library/react";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {useCameraCapture} from "../src/hooks/useCameraCapture";

const send=vi.fn(()=>true),onError=vi.fn(),stop=vi.fn();
const track={stop,addEventListener:vi.fn()};
const stream={getTracks:()=>[track],getVideoTracks:()=>[track]};
const getUserMedia=vi.fn();
function Capture({running=true}:{running?:boolean}) {
  const {videoRef,captureRef}=useCameraCapture("camera",running,send,onError);
  return <><video ref={videoRef}/><canvas ref={captureRef}/></>;
}
beforeEach(()=>{
  vi.useFakeTimers();
  vi.clearAllMocks();
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
  expect(getUserMedia).toHaveBeenCalledWith({video:{facingMode:{ideal:"environment"}},audio:false});
  expect(send).toHaveBeenCalledTimes(5);
  expect(view.container.querySelector("canvas")).toHaveProperty("width",960);
  expect(view.container.querySelector("canvas")).toHaveProperty("height",540);
  view.rerender(<Capture running={false}/>);
  expect(stop).toHaveBeenCalledOnce();
  await act(async()=>{await vi.advanceTimersByTimeAsync(1000);});
  expect(send).toHaveBeenCalledTimes(5);
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
