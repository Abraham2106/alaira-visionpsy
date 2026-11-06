// La captura y el monitor comparten una vista para mantener activo el video.
import { useCallback, useState } from "react";
import AlertBanner from "./AlertBanner";
import AlertPanel from "./AlertPanel";
import MonitorDetails from "./MonitorDetails";
import { monitorTitle } from "../monitorStatus";
import VideoCanvas from "./VideoCanvas";
import { CAPTURE } from "../config";
import { useCameraCapture, type CaptureMode } from "../hooks/useCameraCapture";
import { useCameras } from "../hooks/useCameras";
import { useMonitor } from "../hooks/useMonitor";
import { DEFAULT_CAMERA } from "../frames";
import { useWebSocket } from "../hooks/useWebSocket";
import type { PoseMsg } from "../types";

function poseLabel(pose: PoseMsg | null, synthetic: boolean | undefined) {
  if (pose?.landmarks) return `${pose.landmarks.filter(point => point[2] >= .5).length}/33 puntos`;
  return synthetic ? "Pose sintética" : "Pose";
}

export default function CameraSender({ token, active: visible = true }: { token: string; active?: boolean }) {
  const [mode, setMode] = useState<CaptureMode>("camera");
  const [running, setRunning] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [cameraId, setCameraId] = useState(DEFAULT_CAMERA);
  const [cameraAspect, setCameraAspect] = useState(16 / 9);
  const { cameras, names } = useCameras(token);
  // El servidor asigna cam-1 por defecto; solo se envía camera_id si se elige otra.
  const ingest = useWebSocket("/ws/ingest", token, undefined, running, cameraId === DEFAULT_CAMERA ? undefined : cameraId);
  const monitor = useMonitor(token, running && visible, cameraId);
  const fail = useCallback((message: string) => { setCameraError(message); setRunning(false); }, []);
  const { videoRef, captureRef, frames, resetFrames } = useCameraCapture(mode, running, ingest.send, fail, ingest.canSend);
  const { frame, pose, status, health, alerts } = monitor;
  const streaming = monitor.connected && status?.camera === "streaming";
  const active = alerts.filter((alert) => alert.state !== "RESOLVED").length;
  const statusTitle = running ? monitorTitle(monitor.connected, status) : "Captura detenida";
  const error = cameraError || ingest.error || monitor.error;
  const buttonText = running ? "Detener transmisión" : mode === "camera" ? "Iniciar cámara" : "Transmitir demo";

  function toggleCapture() {
    setCameraError(null); monitor.clearError(); monitor.clearFrame();
    if (!running) resetFrames();
    setRunning((value) => !value);
  }

  return <main className="dashboard">
    {error && <p className="error-box" role="alert">{error}</p>}
    <AlertBanner alerts={alerts} names={names}/>
    <div className="monitor-grid"><section className="monitor-main">
      <section className="panel feed-panel">
        <div className="panel-heading"><h2>Cámara</h2><span className="local-indicator">{running && streaming ? "En directo" : statusTitle}</span></div>
        <div className="camera-preview" style={{ aspectRatio: mode === "camera" ? cameraAspect : 16 / 9 }}>
          <video ref={videoRef} muted playsInline hidden={mode !== "camera"} onResize={(event) => {
            const video = event.currentTarget;
            if (video.videoWidth && video.videoHeight) setCameraAspect(video.videoWidth / video.videoHeight);
          }} />
          <canvas ref={captureRef} hidden={mode === "camera" || frame !== null} />
          {frame && <VideoCanvas frame={frame} pose={pose} overlay={mode === "camera"} videoSource={videoRef} />}
          {!running && <div className="preview-label">Captura detenida</div>}
          <MonitorDetails title={statusTitle} status={status} streaming={streaming} health={health} active={active}/>
        </div>
        <div className="feed-footer"><span><span className="skeleton-key"/>{poseLabel(pose, health?.synthetic)}</span><span>{frames} frames enviados</span></div>
        <div className="camera-controls">
          {cameras.length > 1 && <><label className="field-label" htmlFor="capture-camera">Cámara de la habitación</label>
            <select id="capture-camera" value={cameraId} disabled={running} onChange={(event) => setCameraId(event.target.value)}>
              {cameras.map((camera) => <option key={camera.id} value={camera.id}>{camera.name}</option>)}
            </select></>}
          <label className="field-label" htmlFor="capture-mode">Fuente de imagen</label>
          <select id="capture-mode" value={mode} disabled={running} onChange={(event) => setMode(event.target.value as CaptureMode)}>
            <option value="camera">Cámara de la computadora</option><option value="demo">Demo sintética</option>
          </select>
          <button type="button" className={`button w-full ${running ? "button-outline" : "button-dark"}`} onClick={toggleCapture}>{buttonText}</button>
          <p className="small-note">Hasta {CAPTURE.fps} FPS · JPEG · Sin audio · Sin grabación continua</p>
          <p className="consent-note">Inicia la cámara con el consentimiento de la persona supervisada.</p>
        </div>
      </section>
    </section><aside className="monitor-aside"><AlertPanel alerts={alerts} token={token} onUpdate={monitor.updateAlert} names={names}/></aside></div>
  </main>;
}
