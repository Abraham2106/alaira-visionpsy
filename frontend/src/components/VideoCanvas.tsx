// Compone el frame y el esqueleto visible; cancela dibujos obsoletos y limpia imágenes.
import { useEffect, useRef, type RefObject } from "react";
import type { PoseMsg } from "../types";

const CONNECTIONS = [[0, 1], [1, 2], [2, 3], [3, 7], [0, 4], [4, 5], [5, 6], [6, 8], [9, 10],
  [11, 12], [11, 13], [13, 15], [15, 17], [15, 19], [15, 21], [17, 19],
  [12, 14], [14, 16], [16, 18], [16, 20], [16, 22], [18, 20], [11, 23], [12, 24],
  [23, 24], [23, 25], [25, 27], [27, 29], [27, 31], [29, 31], [24, 26], [26, 28],
  [28, 30], [28, 32], [30, 32]];

export default function VideoCanvas({ frame, pose, overlay = false, videoSource }: { frame: Blob | null; pose: PoseMsg | null; overlay?: boolean; videoSource?: RefObject<HTMLVideoElement | null> }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!frame) return;
    let cancelled = false;
    async function draw() {
      const video = videoSource?.current;
      // The webcam is already playing locally; only remote views need to decode JPEGs.
      const bitmap = overlay && video?.videoWidth ? undefined : await createImageBitmap(frame!);
      const canvas = canvasRef.current;
      if (cancelled || !canvas) { bitmap?.close(); return; }
      const width = bitmap?.width ?? video!.videoWidth, height = bitmap?.height ?? video!.videoHeight;
      if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
      const context = canvas.getContext("2d");
      if (!context) { bitmap?.close(); return; }
      if (overlay) context.clearRect(0, 0, width, height);
      else if (bitmap) context.drawImage(bitmap, 0, 0);
      bitmap?.close();
      const landmarks = pose?.landmarks;
      if (!landmarks) return;
      context.strokeStyle = "#f0ac67";
      context.fillStyle = "#fff1df";
      context.lineWidth = Math.max(2, canvas.width / 300);
      for (const [a, b] of CONNECTIONS) {
        const start = landmarks[a], end = landmarks[b];
        if (!start || !end || start[2] < 0.5 || end[2] < 0.5) continue;
        context.beginPath();
        context.moveTo(start[0] * canvas.width, start[1] * canvas.height);
        context.lineTo(end[0] * canvas.width, end[1] * canvas.height);
        context.stroke();
      }
      for (const [x, y, visibility] of landmarks) {
        if (visibility < 0.5) continue;
        context.beginPath();
        context.arc(x * canvas.width, y * canvas.height, context.lineWidth * 1.7, 0, Math.PI * 2);
        context.fill();
      }
    }
    void draw().catch(() => {
      // Un JPEG incompleto no debe romper el monitor; el siguiente frame vuelve a intentarlo.
    });
    return () => { cancelled = true; };
  }, [frame, pose, overlay, videoSource]);

  return <div className={`video-surface${overlay ? " video-overlay" : ""}`}>
    {frame ? <canvas ref={canvasRef} aria-label="Último frame y esqueleto estimado" />
      : <div className="video-empty"><span className="camera-symbol" aria-hidden="true">⌖</span>
        <h3>Sin señal</h3>
        <a className="button button-light" href="#/camera">Conectar cámara <span aria-hidden="true">↗</span></a></div>}
  </div>;
}
