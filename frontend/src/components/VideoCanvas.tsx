// Compone el frame y el esqueleto visible; cancela dibujos obsoletos y limpia imágenes.
import { useEffect, useRef } from "react";
import type { PoseMsg } from "../types";

const CONNECTIONS = [[0, 1], [1, 2], [2, 3], [3, 7], [0, 4], [4, 5], [5, 6], [6, 8], [9, 10],
  [11, 12], [11, 13], [13, 15], [15, 17], [15, 19], [15, 21], [17, 19],
  [12, 14], [14, 16], [16, 18], [16, 20], [16, 22], [18, 20], [11, 23], [12, 24],
  [23, 24], [23, 25], [25, 27], [27, 29], [27, 31], [29, 31], [24, 26], [26, 28],
  [28, 30], [28, 32], [30, 32]];

export default function VideoCanvas({ frame, pose }: { frame: Blob | null; pose: PoseMsg | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!frame) return;
    let cancelled = false;
    // createImageBitmap no crea object URLs ni deja blobs pendientes de revocar.
    createImageBitmap(frame).then((bitmap) => {
      const canvas = canvasRef.current;
      if (cancelled || !canvas) { bitmap.close(); return; }
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const context = canvas.getContext("2d");
      if (!context) { bitmap.close(); return; }
      context.drawImage(bitmap, 0, 0);
      bitmap.close();
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
    }).catch(() => {
      // Un JPEG incompleto no debe romper el monitor; el siguiente frame vuelve a intentarlo.
    });
    return () => { cancelled = true; };
  }, [frame, pose]);

  return <div className="video-surface">
    {frame ? <canvas ref={canvasRef} aria-label="Último frame y esqueleto estimado" />
      : <div className="video-empty"><span className="camera-symbol" aria-hidden="true">⌖</span>
        <h3>Sin señal</h3>
        <a className="button button-light" href="#/camera">Conectar cámara <span aria-hidden="true">↗</span></a></div>}
  </div>;
}
