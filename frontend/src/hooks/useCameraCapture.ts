// Ciclo de vida de la webcam y codificación JPEG; las imágenes solo viven en memoria.
import { useCallback, useEffect, useRef, useState } from "react";
import { CAPTURE } from "../config";

export type CaptureMode = "camera" | "demo";
type SendFrame = (frame: Blob) => boolean;
const alwaysReady = () => true;

function drawDemo(context: CanvasRenderingContext2D, width: number, height: number) {
  context.fillStyle = "#302822"; context.fillRect(0, 0, width, height);
  context.strokeStyle = "#58483b"; context.lineWidth = 1;
  for (let x = 0; x < width; x += 60) { context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke(); }
  for (let y = 0; y < height; y += 60) { context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke(); }
  context.fillStyle = "#e5cfb8"; context.font = "18px system-ui";
  context.fillText("VisionPsy-Local · frame sintético", 24, 36);
  context.fillText(new Date().toLocaleTimeString(), 24, height - 24);
}

function startCapture(video: HTMLVideoElement, canvas: HTMLCanvasElement, mode: CaptureMode,
  send: SendFrame, onFrame: () => void, onError: (message: string) => void, canSend: () => boolean) {
  let stopped = false;
  let encoding = false;
  let stream: MediaStream | undefined;
  let timer: number | undefined;
  const stop = () => {
    stopped = true;
    window.clearTimeout(timer);
    stream?.getTracks().forEach((track) => track.stop());
    video.srcObject = null;
  };
  const fail = (message: string) => { if (!stopped) { stop(); onError(message); } };

  async function start() {
    if (mode === "camera") {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        fail("La cámara necesita HTTPS con un certificado local de confianza, o localhost.");
        return;
      }
      try {
        const acquired = await navigator.mediaDevices.getUserMedia({ video: {
          facingMode: { ideal: "environment" }, width: { ideal: CAPTURE.maxWidth }, frameRate: { ideal: CAPTURE.fps, max: 30 },
        }, audio: false });
        if (stopped) { acquired.getTracks().forEach((track) => track.stop()); return; }
        stream = acquired;
        stream.getVideoTracks().forEach((track) => track.addEventListener("ended", () => fail("La cámara se desconectó.")));
        video.srcObject = stream;
        await video.play();
      } catch {
        fail("No se pudo abrir la cámara. Revisa el permiso del navegador y si está en uso.");
        return;
      }
    }
    if (stopped) return;
    const context = canvas.getContext("2d");
    if (!context) { fail("No se pudo iniciar el lienzo de captura."); return; }
    const schedule = (delay: number) => { if (!stopped) timer = window.setTimeout(capture, Math.ceil(delay)); };
    const capture = () => {
      if (stopped) return;
      if (document.hidden) { schedule(100); return; }
      // Wait for the previous frame's acknowledgement before drawing or encoding another JPEG.
      if (encoding || !canSend() || (mode === "camera" && !video.videoWidth)) { schedule(8); return; }
      const startedAt = performance.now();
      const width = mode === "camera" ? Math.min(video.videoWidth, CAPTURE.maxWidth) : CAPTURE.maxWidth;
      const height = mode === "camera" ? Math.round(width * video.videoHeight / video.videoWidth) : Math.round(width * 9 / 16);
      if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
      if (mode === "camera") context.drawImage(video, 0, 0, width, height);
      else drawDemo(context, width, height);
      encoding = true;
      canvas.toBlob((blob) => {
        encoding = false;
        if (!stopped && !document.hidden && blob && send(blob)) onFrame();
        schedule(Math.max(0, 1000 / CAPTURE.fps - (performance.now() - startedAt)));
      }, "image/jpeg", CAPTURE.quality);
    };
    schedule(1000 / CAPTURE.fps);
  }
  void start();
  return stop;
}

export function useCameraCapture(mode: CaptureMode, running: boolean, send: SendFrame,
  onError: (message: string) => void, canSend = alwaysReady) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const captureRef = useRef<HTMLCanvasElement>(null);
  const [frames, setFrames] = useState(0);
  const resetFrames = useCallback(() => setFrames(0), []);
  useEffect(() => {
    const video = videoRef.current, canvas = captureRef.current;
    if (!running || !video || !canvas) return;
    return startCapture(video, canvas, mode, send, () => setFrames((count) => count + 1), onError, canSend);
  }, [running, mode, send, onError, canSend]);
  return { videoRef, captureRef, frames, resetFrames };
}
