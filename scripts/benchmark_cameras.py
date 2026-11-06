"""Benchmark E-1: ¿cuántas cámaras aguanta esta PC con un MediaPipePoseEstimator por cámara?

Mide N = 1..4 cámaras a una tasa fija (por defecto 5 FPS cada una), con hilos o con procesos:
latencia p50/p95 de `estimate()`, porcentaje de inferencias por encima de 200 ms, CPU y RSS.
Si falta `mediapipe` o el modelo, el script termina con un mensaje y no inventa resultados.

Ejemplo:
    .venv\\Scripts\\python.exe scripts/benchmark_cameras.py --image foto_persona.jpg --seconds 30
    .venv\\Scripts\\python.exe scripts/benchmark_cameras.py --mode processes --max-cameras 3

Sin `--image` se usa un cuadro sintético sin persona: la detección no encuentra pose y la latencia
resultante puede subestimar la de una escena real. Usa una foto o un fotograma con una persona
visible (se queda en tu PC; el script no la guarda ni la envía).
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import statistics
import sys
import threading
import time
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

THRESHOLD_MS = 200.0


def synthetic_jpeg(width: int = 640, height: int = 360) -> bytes:
    from PIL import Image

    image = Image.new("RGB", (width, height))
    image.putdata([(x * 255 // width, y * 255 // height, 128) for y in range(height) for x in range(width)])
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=80)
    return buffer.getvalue()


def camera_loop(model: str, jpeg: bytes, fps: float, seconds: float, ready: "threading.Barrier | mp.synchronize.Barrier") -> list[float]:
    """Una cámara simulada: un estimador propio, una inferencia por periodo; devuelve latencias en ms."""
    from backend.model_loader import MediaPipePoseEstimator

    estimator = MediaPipePoseEstimator(Path(model))
    latencies: list[float] = []
    period = 1.0 / fps
    try:
        estimator.estimate(jpeg, time.time())  # calentamiento fuera de la medición
        ready.wait()
        end = time.perf_counter() + seconds
        next_tick = time.perf_counter()
        while time.perf_counter() < end:
            started = time.perf_counter()
            estimator.estimate(jpeg, time.time())
            latencies.append((time.perf_counter() - started) * 1000)
            next_tick += period
            delay = next_tick - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = time.perf_counter()  # no acumular deuda: se mide saturación, no recuperación
    finally:
        estimator.close()
    return latencies


def _process_entry(model: str, jpeg: bytes, fps: float, seconds: float, ready, queue) -> None:
    queue.put(camera_loop(model, jpeg, fps, seconds, ready))


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))]


def run_threads(count: int, model: str, jpeg: bytes, fps: float, seconds: float) -> list[float]:
    ready = threading.Barrier(count)
    results: list[list[float]] = [[] for _ in range(count)]
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            results[index] = camera_loop(model, jpeg, fps, seconds, ready)
        except BaseException as error:  # noqa: BLE001 - se informa al final
            errors.append(error)
            ready.abort()

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        raise RuntimeError(f"fallo en una cámara simulada: {errors[0]!r}")
    return [value for chunk in results for value in chunk]


def run_processes(count: int, model: str, jpeg: bytes, fps: float, seconds: float) -> list[float]:
    context = mp.get_context("spawn")
    ready = context.Barrier(count)
    queue = context.Queue()
    processes = [context.Process(target=_process_entry, args=(model, jpeg, fps, seconds, ready, queue)) for _ in range(count)]
    for process in processes:
        process.start()
    latencies: list[float] = []
    for _ in processes:
        latencies.extend(queue.get(timeout=seconds + 120))
    for process in processes:
        process.join()
    return latencies


def sample_resources(stop: threading.Event, out: dict) -> None:
    try:
        import psutil
    except ImportError:
        out["resources"] = "psutil no instalado: CPU y RSS no medidos"
        return
    me = psutil.Process()
    me.cpu_percent(None)
    cpu: list[float] = []
    peak_rss = 0
    while not stop.wait(1.0):
        children = me.children(recursive=True)
        cpu.append(me.cpu_percent(None) + sum(child.cpu_percent(None) for child in children))
        peak_rss = max(peak_rss, me.memory_info().rss + sum(child.memory_info().rss for child in children if child.is_running()))
    if cpu:
        out["cpu_percent_mean"] = round(statistics.fmean(cpu), 1)  # 100 = un núcleo completo
        out["rss_peak_mb"] = round(peak_rss / 1_048_576, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=str(ROOT / "models" / "pose_landmarker_lite.task"))
    parser.add_argument("--image", help="JPEG con una persona visible; sin él se usa un cuadro sin persona")
    parser.add_argument("--mode", choices=("threads", "processes"), default="threads")
    parser.add_argument("--max-cameras", type=int, default=4)
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--seconds", type=float, default=30.0, help="duración de cada N (sin contar calentamiento)")
    args = parser.parse_args()

    try:
        import mediapipe  # noqa: F401
    except ImportError:
        print("mediapipe no está instalado: instala requirements-pose.lock.txt. No se midió nada.", file=sys.stderr)
        return 2
    if not Path(args.model).is_file():
        print(f"Falta el modelo {args.model}: ejecuta scripts/download_pose_model.py. No se midió nada.", file=sys.stderr)
        return 2

    if args.image:
        if not Path(args.image).is_file():
            print(f"No existe la imagen {args.image}: indica la ruta real de un JPEG. No se midió nada.", file=sys.stderr)
            return 2
        jpeg = Path(args.image).read_bytes()
    else:
        jpeg = synthetic_jpeg()
        print("AVISO: cuadro sintético sin persona; la latencia puede subestimar una escena real.", file=sys.stderr)

    runner = run_threads if args.mode == "threads" else run_processes
    rows = []
    for count in range(1, args.max_cameras + 1):
        extra: dict = {}
        stop = threading.Event()
        sampler = threading.Thread(target=sample_resources, args=(stop, extra), daemon=True)
        sampler.start()
        latencies = runner(count, args.model, jpeg, args.fps, args.seconds)
        stop.set()
        sampler.join()
        rows.append({
            "cameras": count,
            "mode": args.mode,
            "target_fps_each": args.fps,
            "samples": len(latencies),
            "achieved_fps_each": round(len(latencies) / count / args.seconds, 2),
            "p50_ms": round(percentile(latencies, 0.50), 1),
            "p95_ms": round(percentile(latencies, 0.95), 1),
            "over_200ms_percent": round(100 * sum(value > THRESHOLD_MS for value in latencies) / len(latencies), 1),
            **extra,
        })
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
