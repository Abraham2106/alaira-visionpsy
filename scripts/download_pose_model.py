"""Descarga el bundle oficial ligero de MediaPipe Pose Landmarker."""
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)
MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "pose_landmarker_lite.task"


def main() -> None:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MODEL_PATH.with_suffix(".task.part")
    try:
        with urlopen(MODEL_URL, timeout=90) as response, temporary.open("wb") as model:
            if urlsplit(response.geturl()).hostname != "storage.googleapis.com":
                raise RuntimeError("El modelo redirigió a un host no esperado")
            while chunk := response.read(1024 * 1024):
                model.write(chunk)
        if temporary.stat().st_size < 1_000_000:
            raise RuntimeError("La descarga no parece ser un bundle MediaPipe válido")
        temporary.replace(MODEL_PATH)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Modelo MediaPipe listo: {MODEL_PATH}")


if __name__ == "__main__":
    main()
