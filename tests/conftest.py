# Fixtures sintéticas y recolector de eventos: los tests no usan modelos, cámara ni red.
import secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import Settings


class CollectSink:
    def __init__(self):
        self.messages: list[dict] = []
        self.frames: list[bytes] = []
        self.frame_cameras: list[str] = []

    async def emit(self, message: dict):
        self.messages.append(message)

    async def emit_frame(self, camera_id: str, jpeg: bytes):
        self.frame_cameras.append(camera_id)
        self.frames.append(jpeg)


@pytest.fixture
def settings():
    return Settings(token=secrets.token_urlsafe(24))


@pytest.fixture
def sink():
    return CollectSink()


@pytest.fixture
def jpeg():
    # El stub no decodifica píxeles; el transporte comprueba delimitadores y tamaño.
    return b"\xff\xd8synthetic-test-frame\xff\xd9"
