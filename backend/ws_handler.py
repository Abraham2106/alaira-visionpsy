# Adapta WebSocket al pipeline con token inicial, origen restringido y control de clientes caídos.
import asyncio
import secrets
from json import JSONDecodeError

from fastapi import WebSocket, WebSocketDisconnect

from .config import Settings
from .pipeline import InvalidFrame, Pipeline


async def authenticate(ws: WebSocket, settings: Settings, camera_authorized=None) -> bool:
    origin = ws.headers.get("origin")
    if origin is not None and origin not in settings.server.allowed_origins:
        await ws.close(code=1008)
        return False
    await ws.accept()
    try:
        message = await asyncio.wait_for(ws.receive_json(), settings.server.auth_timeout_seconds)
        token = message.get("token") if isinstance(message, dict) else None
        is_admin = isinstance(token, str) and secrets.compare_digest(token.encode(), settings.token.encode())
        owner = camera_authorized(token) if (camera_authorized is not None and isinstance(token, str) and not is_admin) else None
        if not isinstance(message, dict) or message.get("type") != "auth" or not isinstance(token, str) or not (is_admin or owner):
            await ws.close(code=1008, reason="Autenticación requerida")
            return False
        if owner:
            # La identidad de la cámara la fija la credencial; el cliente no puede elegirla.
            ws.state.camera_id = owner
            ws.state.camera_authorized = lambda: camera_authorized(token) == owner
        else:
            requested = message.get("camera_id")
            ws.state.camera_id = requested if isinstance(requested, str) else "cam-1"
        ws.state.flow_control = message.get("flow_control") is True
    except (WebSocketDisconnect, RuntimeError):
        return False
    except (TimeoutError, JSONDecodeError, KeyError):
        try:
            await ws.close(code=1008)
        except (WebSocketDisconnect, RuntimeError):
            pass
        return False
    return True


def frame_packet(camera_id: str, jpeg: bytes) -> bytes:
    """[1 byte: longitud][camera_id UTF-8][JPEG]; el dashboard enruta cada frame a su cámara."""
    name = camera_id.encode()
    return bytes([len(name)]) + name + jpeg


class ConnectionManager:
    def __init__(self, timeout_seconds: float = 2):
        self.clients: set[WebSocket] = set()
        self.producers: dict[str, WebSocket] = {}
        self.timeout_seconds = timeout_seconds

    @property
    def producer(self) -> WebSocket | None:
        """Compatibilidad: productor de la cámara principal."""
        return self.producers.get("cam-1")

    async def _send(self, ws: WebSocket, message: dict | bytes) -> None:
        try:
            operation = ws.send_bytes(message) if isinstance(message, bytes) else ws.send_json(message)
            await asyncio.wait_for(operation, self.timeout_seconds)
        except Exception:
            self.clients.discard(ws)
            try:
                await asyncio.wait_for(ws.close(code=1011), self.timeout_seconds)
            except Exception:
                pass

    async def emit(self, message: dict) -> None:
        await asyncio.gather(*(self._send(ws, message) for ws in tuple(self.clients)))

    async def emit_frame(self, camera_id: str, jpeg: bytes) -> None:
        packet = frame_packet(camera_id, jpeg)
        await asyncio.gather(*(self._send(ws, packet) for ws in tuple(self.clients)))


async def handle_dashboard(ws: WebSocket, manager: ConnectionManager, pipelines) -> None:
    """``pipelines``: un Pipeline o un dict camera_id -> Pipeline."""
    group = {"cam-1": pipelines} if isinstance(pipelines, Pipeline) else pipelines
    manager.clients.add(ws)
    try:
        for pipeline in group.values():
            await ws.send_json(pipeline.last_status.model_dump(mode="json"))
        sent = set()
        for pipeline in group.values():
            for alert in pipeline.snapshot():
                if alert["id"] not in sent:
                    sent.add(alert["id"])
                    await ws.send_json(alert)
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        manager.clients.discard(ws)


async def handle_ingest(ws: WebSocket, manager: ConnectionManager, pipelines) -> None:
    group = {"cam-1": pipelines} if isinstance(pipelines, Pipeline) else pipelines
    camera_id = getattr(ws.state, "camera_id", "cam-1")
    pipeline = group.get(camera_id)
    if pipeline is None:
        await ws.close(code=1008, reason="Cámara desconocida")
        return
    if camera_id in manager.producers:
        await ws.close(code=1008, reason="Ya hay una cámara conectada")
        return
    manager.producers[camera_id] = ws
    try:
        while True:
            event = await ws.receive()
            if event["type"] == "websocket.disconnect":
                break
            frame = event.get("bytes")
            checker = getattr(ws.state, "camera_authorized", None)
            if checker is not None and not checker():
                await ws.close(code=1008, reason="Cámara desvinculada")
                break
            if frame is None:
                await ws.close(code=1003, reason="Envía JPEG binario")
                break
            try:
                await pipeline.process(frame)
                if getattr(ws.state, "flow_control", False):
                    await ws.send_json({"type":"processed"})
            except InvalidFrame as error:
                await ws.close(code=1009 if len(frame) > pipeline.settings.server.max_frame_bytes else 1003,
                               reason=str(error))
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if manager.producers.get(camera_id) is ws:
            del manager.producers[camera_id]
        await pipeline.camera_disconnected()
