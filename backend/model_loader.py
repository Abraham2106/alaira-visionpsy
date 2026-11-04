# Registro de backends: simuladores ejecutables y conectores reales explícitamente pendientes.
import asyncio
from io import BytesIO
from pathlib import Path
import threading

from .config import Settings
from .interfaces import Landmark, Pose, PoseEstimator, VisionAnswer, VisionModel


class ModelLoadError(RuntimeError):
    pass


def synthetic_pose(timestamp: float, lying: bool = False, aspect: float = 16 / 9) -> Pose:
    points = [Landmark(0.5, 0.5, 0) for _ in range(33)]
    joints = ({11: (0.27, 0.76), 12: (0.27, 0.83), 23: (0.55, 0.76), 24: (0.55, 0.83),
               13: (0.37, 0.87), 14: (0.37, 0.92), 15: (0.48, 0.88), 16: (0.48, 0.94),
               25: (0.7, 0.77), 26: (0.7, 0.84), 27: (0.86, 0.77), 28: (0.86, 0.84)}
              if lying else
              {11: (0.43, 0.25), 12: (0.57, 0.25), 23: (0.46, 0.55), 24: (0.54, 0.55),
               13: (0.39, 0.4), 14: (0.61, 0.4), 15: (0.38, 0.53), 16: (0.62, 0.53),
               25: (0.45, 0.73), 26: (0.55, 0.73), 27: (0.44, 0.9), 28: (0.56, 0.9)})
    for index, (x, y) in joints.items():
        points[index] = Landmark(x, y)
    return Pose(tuple(points), timestamp, aspect)


class StubPoseEstimator:
    # El stub no decodifica la imagen; declara el 16:9 habitual de la webcam.
    def __init__(self, scenario: str = "standing", cycle_seconds: float = 24):
        if scenario not in {"standing", "fall", "demo"}:
            raise ModelLoadError(f"Escenario sintético desconocido: {scenario}")
        self.scenario, self.cycle_seconds = scenario, cycle_seconds
        self.started_at: float | None = None

    def estimate(self, jpeg: bytes, timestamp: float) -> Pose:
        if self.started_at is None:
            self.started_at = timestamp
        elapsed = (timestamp - self.started_at) % self.cycle_seconds
        lying = self.scenario == "fall" or (self.scenario == "demo" and 3 <= elapsed < 14)
        return synthetic_pose(timestamp, lying)


class StubVisionModel:
    async def ask(self, jpeg: bytes, question: str) -> VisionAnswer:
        await asyncio.sleep(0)
        return VisionAnswer("[stub] Respuesta sintética; la imagen no fue analizada por IA.")


def _mediapipe(settings: Settings) -> PoseEstimator:
    model_path = Path(settings.models.pose.model_path)
    if not model_path.is_absolute():
        model_path = (Path(__file__).parent / model_path).resolve()
    if not model_path.is_file():
        raise ModelLoadError(
            f"No se encuentra el modelo MediaPipe: {model_path}. "
            "Descárgalo con python scripts/download_pose_model.py"
        )
    return MediaPipePoseEstimator(model_path)


class MediaPipePoseEstimator:
    """MediaPipe Pose Landmarker en modo vídeo, con un modelo reutilizado por cámara."""

    def __init__(self, model_path: Path):
        try:
            import mediapipe as mp
            import numpy as np
            from PIL import Image
        except ImportError as error:
            raise ModelLoadError(
                "Faltan dependencias de MediaPipe; instala requirements-pose.txt"
            ) from error

        self._mp, self._np, self._image = mp, np, Image
        self._lock = threading.Lock()
        self._last_timestamp_ms = -1
        try:
            options = mp.tasks.vision.PoseLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_poses=1,
            )
            self._landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(options)
        except Exception as error:
            raise ModelLoadError(f"No se pudo cargar el modelo MediaPipe: {error}") from error

    def estimate(self, jpeg: bytes, timestamp: float) -> Pose | None:
        try:
            with self._image.open(BytesIO(jpeg)) as source:
                width, height = source.size
                rgb = self._np.array(source.convert("RGB"), dtype=self._np.uint8, copy=True)
            aspect = width / height if width and height else 1.0
            mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
            with self._lock:
                timestamp_ms = max(int(timestamp * 1000), self._last_timestamp_ms + 1)
                result = self._landmarker.detect_for_video(mp_image, timestamp_ms)
                self._last_timestamp_ms = timestamp_ms
            if not result.pose_landmarks:
                return None
            landmarks = result.pose_landmarks[0]
            if len(landmarks) != 33:
                raise ValueError(f"MediaPipe devolvió {len(landmarks)} puntos; se esperaban 33")
            return Pose(tuple(Landmark(
                x=float(point.x), y=float(point.y),
                visibility=float(point.visibility or 0.0),
            ) for point in landmarks), timestamp, aspect)
        except Exception as error:
            if isinstance(error, ValueError) and str(error).startswith("MediaPipe devolvió"):
                raise
            raise ValueError("No se pudo procesar el JPEG con MediaPipe Pose") from error

    def close(self) -> None:
        with self._lock:
            self._landmarker.close()


def _llamacpp(settings: Settings) -> VisionModel:
    if not Path(settings.models.vision.gguf_path).is_file():
        raise ModelLoadError("No se encuentra el GGUF configurado en models.vision.gguf_path")
    # TODO: cargar GGUF + proyector multimodal y ejecutar llama.cpp fuera del event loop.
    raise NotImplementedError("llama.cpp pendiente: conecta VisionModel en model_loader.py")


def _qvac(settings: Settings) -> VisionModel:
    # TODO: conectar el QVAC SDK local y adaptar su respuesta a VisionAnswer.
    raise NotImplementedError("QVAC SDK pendiente: conecta VisionModel en model_loader.py")


def _visionpsy(settings: Settings) -> VisionModel:
    try:
        from .visionpsy import VisionPsyModel
        config = settings.models.vision
        return VisionPsyModel(
            executable=config.executable, model_path=config.gguf_path,
            mmproj_path=config.mmproj_path, runtime_library_dirs=tuple(config.runtime_library_dirs),
            port=config.port, gpu_layers=config.gpu_layers, max_tokens=config.max_tokens,
            timeout_seconds=config.timeout_seconds, startup_timeout_seconds=config.startup_timeout_seconds,
            max_image_bytes=settings.server.max_frame_bytes,
        )
    except (ImportError, ValueError) as error:
        raise ModelLoadError(
            f"No se pudo configurar VisionPsy: {error}. Instala requirements-visionpsy.txt "
            "y prepara los pesos y llama-server parcheado."
        ) from error


POSE_BACKENDS = {"stub": lambda s: StubPoseEstimator(s.models.pose.scenario, s.models.pose.demo_cycle_seconds),
                 "mediapipe": _mediapipe}
VISION_BACKENDS = {"stub": lambda s: StubVisionModel(), "llamacpp": _llamacpp, "qvac": _qvac,
                   "visionpsy": _visionpsy}


def _load(registry, name: str, settings: Settings):
    if name not in registry:
        raise ModelLoadError(f"Backend desconocido: {name}; opciones: {', '.join(registry)}")
    return registry[name](settings)


def load_pose_estimator(settings: Settings) -> PoseEstimator:
    return _load(POSE_BACKENDS, settings.models.pose.backend, settings)


def load_vision_model(settings: Settings) -> VisionModel:
    return _load(VISION_BACKENDS, settings.models.vision.backend, settings)
