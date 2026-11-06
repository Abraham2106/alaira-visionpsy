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
from .consolidator import RoomConsolidator
from .messages import PoseMsg, StatusMsg
from .risk import Assessment
from .fall_detector import TemporalFallDetector

log = logging.getLogger(__name__)


class InvalidFrame(ValueError):
    pass


class Pipeline:
    def __init__(self, settings: Settings, estimator: PoseEstimator, vision: VisionModel,
                 sink: EventSink, clock: Callable[[], float] = time.time, *, repository=None,
                 camera_id: str = "cam-1", alerts: AlertStore | None = None, technical: AlertStore | None = None,
                 room: RoomConsolidator | None = None):
        self.settings, self.estimator, self.vision = settings, estimator, vision
        self.sink, self.clock = sink, clock
        self.camera_id = camera_id
        self.detector = TemporalFallDetector()
        self.pose_latency_ms = 0.0
        self.history = deque(maxlen=settings.pipeline.history_size)
        # Almacenes inyectables: la alerta de caídas se comparte por habitación; la técnica es por cámara.
        self.alerts = alerts or (room.alerts if room is not None else AlertStore(settings.alerts, sink, repository=repository))
        self.technical = technical or AlertStore(settings.alerts, sink, repository=repository, kind="technical",
                                                 camera_id=camera_id if room is not None else None)
        self.room = room
        if room is not None:
            room.register(camera_id, self)
        self.last_frame: float | None = None
        self.last_status = StatusMsg(timestamp=clock(), level="ok", reasons=[], camera="waiting", camera_id=camera_id)
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    def snapshot(self):
        if self.room is not None:
            return self.room.snapshot()
        return sorted(self.alerts.snapshot()+self.technical.snapshot(),key=lambda item:item["timestamp"])[-100:]

    async def act(self,event_id,action,reason,now):
        if self.room is not None:
            return await self.room.act(event_id,action,reason,now)
        try:
            return await self.alerts.act(event_id,action,reason,now)
        except KeyError:
            return await self.technical.act(event_id,action,reason,now)

    async def _observe(self, result: Assessment | None, now: float) -> None:
        if self.room is not None:
            await self.room.observe(self.camera_id, result, now)
        else:
            await self.alerts.observe(result, now)

    async def _critical(self, result: Assessment, now: float):
        if self.room is not None:
            return await self.room.critical(self.camera_id, result, now)
        return await self.alerts.open(result, now, self.camera_id)

    async def _status(self, result: Assessment, now: float, camera: str, error: str | None = None) -> None:
        self.last_status = StatusMsg(camera_id=self.camera_id, timestamp=now, level=result.level, reasons=list(result.reasons),
                                     camera=camera, model_error=error,
                                     diagnostics={**self.detector.diagnostics(), "latency_ms": round(self.pose_latency_ms, 1)})
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
                await self._observe(None, ts)
            self.last_frame = ts
            await self.sink.emit_frame(self.camera_id, jpeg)
            try:
                inference_started = time.perf_counter()
                pose = await asyncio.to_thread(self.estimator.estimate, jpeg, ts)
                self.pose_latency_ms = (time.perf_counter()-inference_started)*1000
                message = PoseMsg(camera_id=self.camera_id, timestamp=ts, landmarks=None if pose is None else
                                  [(point.x, point.y, point.visibility) for point in pose.landmarks])
            except Exception:
                log.exception("Fallo del estimador de pose")
                self.history.clear()
                self.detector.update(None, ts, self.settings.risk)
                await self._observe(None, ts)
                await self.sink.emit(PoseMsg(camera_id=self.camera_id, timestamp=ts).model_dump(mode="json"))
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
            result = self.detector.update(pose, ts, self.settings.risk)
            capacity_limited = (len(self.history) == self.history.maxlen
                and self.history[-1].timestamp - self.history[0].timestamp < self.settings.risk.immobile_seconds
                and "no_pose" not in result.reasons)
            if capacity_limited:
                result = Assessment(result.level, (*result.reasons, "insufficient_history"))
            await self._status(result, ts, "streaming")
            await self._observe(None if capacity_limited else result, ts)
            if result.level == "critical":
                alert = await self._critical(result, ts)
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
        self.detector.reset()
        self.history.clear()
        self.last_frame = None
        await self._observe(None, now)
        await self.sink.emit(PoseMsg(camera_id=self.camera_id, timestamp=now).model_dump(mode="json"))
        await self._status(Assessment("ok", ("camera_disconnected",)), now, "disconnected")
        if was_streaming:
            await self.technical.open(Assessment("suspect",("camera_disconnected",)),now,self.camera_id)

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
