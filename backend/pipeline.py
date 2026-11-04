# Coordina captura, pose, riesgo y alertas mediante contratos sin conocer WebSocket o P2P.
import asyncio
import logging
import math
import time
from collections import deque
from collections.abc import Callable

from .alert_lifecycle import AlertStore
from .config import Settings
from .interfaces import EventSink, PoseEstimator, VisionModel
from .messages import PoseMsg, StatusMsg
from .risk import Assessment, assess

log = logging.getLogger(__name__)


class InvalidFrame(ValueError):
    pass


class Pipeline:
    def __init__(self, settings: Settings, estimator: PoseEstimator, vision: VisionModel,
                 sink: EventSink, clock: Callable[[], float] = time.time, *, repository=None):
        self.settings, self.estimator, self.vision = settings, estimator, vision
        self.sink, self.clock = sink, clock
        self.history = deque(maxlen=settings.pipeline.history_size)
        self.alerts = AlertStore(settings.alerts, sink, repository=repository)
        self.technical = AlertStore(settings.alerts, sink, repository=repository, kind="technical")
        self.last_frame: float | None = None
        self.last_status = StatusMsg(timestamp=clock(), level="ok", reasons=[], camera="waiting")
        # ponytail: una cámara por proceso; separar pipelines por cámara al añadir multifuente.
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    def snapshot(self):
        return sorted(self.alerts.snapshot()+self.technical.snapshot(),key=lambda item:item["timestamp"])[-100:]

    async def act(self,event_id,action,reason,now):
        try:
            return await self.alerts.act(event_id,action,reason,now)
        except KeyError:
            return await self.technical.act(event_id,action,reason,now)

    async def _status(self, result: Assessment, now: float, camera: str, error: str | None = None) -> None:
        self.last_status = StatusMsg(timestamp=now, level=result.level, reasons=list(result.reasons),
                                     camera=camera, model_error=error)
        await self.sink.emit(self.last_status.model_dump(mode="json"))

    async def process(self, jpeg: bytes, now: float | None = None) -> None:
        if len(jpeg) > self.settings.server.max_frame_bytes:
            raise InvalidFrame("Frame demasiado grande")
        if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
            raise InvalidFrame("Se esperaba un frame JPEG binario")
        ts = self.clock() if now is None else now
        if not math.isfinite(ts):
            raise InvalidFrame("Timestamp inválido")
        async with self._lock:
            await self.technical.recover_technical(ts)
            if self.last_frame is not None and not (0 < ts - self.last_frame <= self.settings.risk.max_pose_gap_seconds):
                self.history.clear()
                await self.alerts.observe(None, ts)
            self.last_frame = ts
            await self.sink.emit_frame(jpeg)
            try:
                pose = await asyncio.to_thread(self.estimator.estimate, jpeg, ts)
                message = PoseMsg(timestamp=ts, landmarks=None if pose is None else
                                  [(point.x, point.y, point.visibility) for point in pose.landmarks])
            except Exception:
                log.exception("Fallo del estimador de pose")
                self.history.clear()
                await self.alerts.observe(None, ts)
                await self.sink.emit(PoseMsg(timestamp=ts).model_dump(mode="json"))
                await self._status(Assessment("ok", ("model_error",)), ts, "streaming", "Fallo del estimador de pose")
                return
            await self.sink.emit(message.model_dump(mode="json"))
            if pose is None:
                self.history.clear()
            else:
                self.history.append(pose)
                # Ventana por tiempo: independiente de los FPS y acotada además por maxlen.
                cutoff = ts - self.settings.pipeline.history_seconds
                while self.history and self.history[0].timestamp < cutoff:
                    self.history.popleft()
            result = assess(list(self.history), self.settings.risk)
            capacity_limited = (len(self.history) == self.history.maxlen
                and self.history[-1].timestamp - self.history[0].timestamp < self.settings.risk.immobile_seconds
                and "no_pose" not in result.reasons)
            if capacity_limited:
                result = Assessment(result.level, (*result.reasons, "insufficient_history"))
            await self._status(result, ts, "streaming")
            await self.alerts.observe(None if capacity_limited else result, ts)
            if result.level == "critical":
                alert = await self.alerts.open(result, ts)
                if alert is not None:
                    task = asyncio.create_task(self._confirm(alert.id, jpeg))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)

    async def _confirm(self, alert_id: str, jpeg: bytes) -> None:
        text, error = None, None
        try:
            answer = await asyncio.wait_for(self.vision.ask(jpeg, self.settings.pipeline.vision_question),
                                            timeout=self.settings.models.vision.timeout_seconds)
            text = answer.text
        except TimeoutError:
            error = "Tiempo de análisis visual agotado"
        except Exception:
            log.exception("Fallo del modelo de visión")
            error = "Fallo del modelo de visión"
        await self.alerts.set_vision(alert_id, text, error, self.clock())

    async def camera_disconnected(self, now: float | None = None) -> None:
        async with self._lock:
            await self._disconnect(self.clock() if now is None else now)

    async def _disconnect(self, now: float) -> None:
        was_streaming = self.last_frame is not None
        self.history.clear()
        self.last_frame = None
        await self.alerts.observe(None, now)
        await self.sink.emit(PoseMsg(timestamp=now).model_dump(mode="json"))
        await self._status(Assessment("ok", ("camera_disconnected",)), now, "disconnected")
        if was_streaming:
            await self.technical.open(Assessment("suspect",("camera_disconnected",)),now)

    async def tick(self, now: float | None = None) -> None:
        ts = self.clock() if now is None else now
        async with self._lock:
            if self.last_frame is not None and ts - self.last_frame >= self.settings.server.camera_timeout_seconds:
                await self._disconnect(ts)
            await self.alerts.expire(ts)

    async def close(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
