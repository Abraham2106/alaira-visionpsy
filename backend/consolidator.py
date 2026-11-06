"""Consolidación por habitación: varias cámaras, una sola alerta de caída.

Reglas: cualquier ``critical`` abre (o amplía las ``sources`` de) la alerta; solo se resuelve cuando todas las
cámaras con pose utilizable reportan ``ok``; ``no_pose`` o una cámara desconectada nunca veta la resolución;
una cámara nunca suprime a otra.
"""

from .alert_lifecycle import AlertStore
from .messages import AlertMsg
from .risk import Assessment


class RoomConsolidator:
    def __init__(self, alerts: AlertStore, stale_seconds: float = 1.0):
        self.alerts = alerts
        self.stale_seconds = stale_seconds
        self.latest: dict[str, tuple[Assessment, float]] = {}
        self.pipelines: dict[str, object] = {}

    def merged(self, now: float) -> Assessment | None:
        usable = [result for result, at in self.latest.values()
                  if now - at <= self.stale_seconds and "no_pose" not in result.reasons]
        if not usable:
            return None
        if any(result.level == "critical" for result in usable):
            return Assessment("critical", tuple(sorted({r for item in usable for r in item.reasons})))
        if any(result.level != "ok" for result in usable):
            return Assessment("suspect", tuple(sorted({r for item in usable for r in item.reasons})))
        return Assessment("ok", ())

    async def observe(self, camera_id: str, assessment: Assessment | None, now: float) -> None:
        if assessment is None:
            self.latest.pop(camera_id, None)
        else:
            self.latest[camera_id] = (assessment, now)
        await self.alerts.observe(self.merged(now), now)

    async def critical(self, camera_id: str, assessment: Assessment, now: float) -> AlertMsg | None:
        """Devuelve la alerta solo si se acaba de abrir (para lanzar la confirmación visual una vez)."""
        opened = await self.alerts.open(assessment, now, camera_id)
        if opened is None:
            await self.alerts.add_source(camera_id, now)
        return opened

    def register(self, camera_id: str, pipeline) -> None:
        self.pipelines[camera_id] = pipeline

    def snapshot(self) -> list[dict]:
        items = {item["id"]: item for item in self.alerts.snapshot()}
        for pipeline in self.pipelines.values():
            items.update({item["id"]: item for item in pipeline.technical.snapshot()})
        return sorted(items.values(), key=lambda item: item["timestamp"])[-100:]

    async def act(self, event_id: str, action: str, reason: str, now: float):
        try:
            return await self.alerts.act(event_id, action, reason, now)
        except KeyError:
            pass
        for pipeline in self.pipelines.values():
            try:
                return await pipeline.technical.act(event_id, action, reason, now)
            except KeyError:
                continue
        raise KeyError(event_id)

    async def acknowledge(self, event_id: str, now: float) -> AlertMsg:
        return await self.alerts.acknowledge(event_id, now)
