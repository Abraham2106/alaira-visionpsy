# Contratos de pose, visión y salida de eventos independientes del transporte.
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Landmark:
    x: float
    y: float
    visibility: float = 1.0


@dataclass(frozen=True)
class Pose:
    landmarks: tuple[Landmark, ...]
    timestamp: float
    # Relación ancho/alto del frame original; corrige la anisotropía de x e y normalizadas.
    aspect: float = 1.0


@dataclass(frozen=True)
class VisionAnswer:
    text: str


class PoseEstimator(Protocol):
    def estimate(self, jpeg: bytes, timestamp: float) -> Pose | None:
        """Devuelve 33 landmarks normalizados o None si no hay pose."""


class VisionModel(Protocol):
    async def ask(self, jpeg: bytes, question: str) -> VisionAnswer:
        """Analiza una sola imagen sin bloquear el bucle de eventos."""


class EventSink(Protocol):
    async def emit(self, message: dict) -> None:
        """Entrega un mensaje JSON a los consumidores."""

    async def emit_frame(self, camera_id: str, jpeg: bytes) -> None:
        """Entrega un JPEG en memoria a los consumidores."""
