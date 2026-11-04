"""Ensayo corto de MediaPipe real + WSS; no sustituye la aceptación del teléfono."""
import argparse
import io
import json
import ssl
import statistics
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from PIL import Image
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import load_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--cert-dir", type=Path, default=ROOT / "certs/autonomous")
    args = parser.parse_args()
    if not 6 <= args.seconds <= 120:
        parser.error("Usa entre 6 y 120 segundos")
    context = ssl.create_default_context(cafile=str(args.cert_dir / "ca.pem"))
    settings = load_settings()
    output = io.BytesIO()
    Image.new("RGB", (640, 480), (45, 45, 45)).save(output, format="JPEG")
    jpeg = output.getvalue()
    url = "https://127.0.0.1:5175"
    request = Request(url + "/api/health", headers={"Authorization": "Bearer " + settings.token})
    report_path = ROOT / "reports/camera-transport.json"
    report_path.parent.mkdir(exist_ok=True)
    latencies = []
    reconnects = 0
    started = None
    report = {"input": "synthetic blank JPEG; no person", "pose_backend": "mediapipe",
              "transport": "HTTPS/WSS with verified local CA", "physical_phone_test": False}
    with (ROOT / "reports/camera-transport.log").open("w", encoding="utf-8") as log:
        supervisor = subprocess.Popen([sys.executable, str(ROOT / "scripts/run_local.py"),
            "--mode", "real", "--cert-dir", str(args.cert_dir),
            "--database", str(ROOT / "data/camera-transport.sqlite3"),
            "--runtime-seconds", str(args.seconds + 5)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 45
            while True:
                if supervisor.poll() is not None:
                    raise RuntimeError("El supervisor terminó antes de estar listo")
                try:
                    with urlopen(request, context=context, timeout=2) as response:
                        health = json.load(response)
                    assert health["pose"] == "mediapipe", health
                    break
                except (URLError, OSError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("El servicio no arrancó")
                    time.sleep(.25)
            started = time.monotonic()
            for segment in range(4):
                with connect(url.replace("https:", "wss:") + "/ws/ingest", ssl=context,
                             origin=url, proxy=None, close_timeout=2) as ws:
                    ws.send(json.dumps({"type": "auth", "token": settings.token, "flow_control": True}))
                    segment_end = started + args.seconds * (segment + 1) / 4
                    while time.monotonic() < segment_end:
                        sent = time.monotonic()
                        ws.send(jpeg)
                        assert json.loads(ws.recv(timeout=4))["type"] == "processed"
                        latencies.append(time.monotonic() - sent)
                        time.sleep(max(0, .2 - (time.monotonic() - sent)))
                if segment < 3:
                    reconnects += 1
                    time.sleep(.25)
                print(f"Tramo {segment + 1}/4: {len(latencies)} frames procesados", flush=True)
            report.update(result="passed", duration_seconds=round(time.monotonic() - started, 2),
                frames=len(latencies), reconnects=reconnects,
                processed_fps=round(len(latencies) / (time.monotonic() - started), 2),
                latency_ms_median=round(statistics.median(latencies) * 1000, 2),
                latency_ms_max=round(max(latencies) * 1000, 2))
        except Exception as error:
            report.update(result="failed", error=type(error).__name__)
            raise
        finally:
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            # El supervisor termina y libera sus dos hijos por su propio plazo.
            supervisor.wait(timeout=args.seconds + 65)
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
