"""Descarga el bundle oficial ligero de MediaPipe Pose Landmarker."""
from pathlib import Path
import hashlib
from urllib.parse import urlsplit
from urllib.request import urlopen


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)
MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "pose_landmarker_lite.task"
MODEL_SHA256 = "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a"


def main() -> None:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if MODEL_PATH.is_file() and hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == MODEL_SHA256:
        return
    temporary = MODEL_PATH.with_suffix(".task.part")
    try:
        with urlopen(MODEL_URL, timeout=90) as response, temporary.open("wb") as model:
            if urlsplit(response.geturl()).hostname != "storage.googleapis.com":
                raise RuntimeError("El modelo redirigió a un host no esperado")
            while chunk := response.read(1024 * 1024):
                model.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != MODEL_SHA256:
            raise RuntimeError("El modelo descargado no coincide con el SHA-256 oficial fijado")
        temporary.replace(MODEL_PATH)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Modelo MediaPipe listo: {MODEL_PATH}")


if __name__ == "__main__":
    main()
