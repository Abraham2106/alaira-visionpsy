# Única máquina de estados: transiciones puras y almacén en memoria con deduplicación.
import asyncio
import uuid
from typing import Literal

from .config import AlertConfig
from .interfaces import EventSink
from .messages import AlertMsg, AlertState
from .risk import Assessment

AlertEvent = Literal["acknowledge", "auto_resolve", "expire"]
TRANSITIONS: dict[tuple[AlertState, AlertEvent], AlertState] = {
    ("OPEN", "acknowledge"): "ACKNOWLEDGED",
    ("OPEN", "auto_resolve"): "RESOLVED",
    ("OPEN", "expire"): "RESOLVED",
    ("ACKNOWLEDGED", "auto_resolve"): "RESOLVED",
    ("ACKNOWLEDGED", "expire"): "RESOLVED",
}


class IllegalTransition(ValueError):
    pass


def transition(state: AlertState, event: AlertEvent) -> AlertState:
    try:
        return TRANSITIONS[(state, event)]
    except KeyError as error:
        raise IllegalTransition(f"Transición ilegal: {state} + {event}") from error


class AlertStore:
    def __init__(self, config: AlertConfig, sink: EventSink, repository=None, kind="fall"):
        self.config, self.sink = config, sink
        self.history: dict[str, AlertMsg] = {}
        self.active_id: str | None = None
        self.ok_since: float | None = None
        self._lock = asyncio.Lock()
        self.repository = repository
        self.kind = kind
        if repository is not None:
            self.history = {alert.id: alert for alert in repository.alerts(config.history_size, kind)}
            self.active_id = next((a.id for a in reversed(list(self.history.values())) if a.state != "RESOLVED"), None)

    def snapshot(self) -> list[dict]:
        return [alert.model_dump(mode="json") for alert in self.history.values()]

    async def _publish(self, alert: AlertMsg, action=None, reason="") -> AlertMsg:
        if self.repository is not None:
            await asyncio.to_thread(self.repository.save_alert, alert, action, reason)
        self.history[alert.id] = alert
        await self.sink.emit(alert.model_dump(mode="json"))
        return alert

    async def _apply(self, alert: AlertMsg, event: AlertEvent, now: float) -> AlertMsg:
        updated = alert.model_copy(update={"state": transition(alert.state, event), "event": event, "updated_at": now})
        if event == "acknowledge":
            updated = updated.model_copy(update={"attention": "attending"})
        elif event == "auto_resolve":
            updated = updated.model_copy(update={"recovery_at": now})
        elif event == "expire" and alert.attention == "pending":
            updated = updated.model_copy(update={"attention": "expired"})
        result = await self._publish(updated, event)
        if updated.state == "RESOLVED":
            self.active_id, self.ok_since = None, None
        return result

    async def open(self, assessment: Assessment, now: float) -> AlertMsg | None:
        async with self._lock:
            if self.active_id is not None:
                return None
            while len(self.history) >= self.config.history_size:
                del self.history[next(iter(self.history))]
            zones = await asyncio.to_thread(self.repository.zones) if self.repository is not None else None
            alert = AlertMsg(id=uuid.uuid4().hex, timestamp=now, updated_at=now,
                             level=assessment.level, reasons=list(assessment.reasons), state="OPEN", kind=self.kind, zones=zones)
            result = await self._publish(alert)
            self.active_id, self.ok_since = alert.id, None
            return result

    async def acknowledge(self, alert_id: str, now: float) -> AlertMsg:
        async with self._lock:
            return await self._apply(self.history[alert_id], "acknowledge", now)

    async def act(self, alert_id: str, action: str, reason: str, now: float) -> AlertMsg:
        target = {"attend": "attending", "discard": "discarded", "close": "closed"}[action]
        async with self._lock:
            alert = self.history.get(alert_id)
            if alert is None and self.repository is not None:
                alert = await asyncio.to_thread(self.repository.alert,alert_id)
                if alert.kind != self.kind:
                    raise KeyError(alert_id)
            if alert is None:
                raise KeyError(alert_id)
            if alert.attention == target:
                return alert
            if alert.attention in {"discarded", "closed"}:
                raise IllegalTransition("El evento ya está cerrado")
            if action == "discard" and not reason.strip():
                raise IllegalTransition("Indica por qué se descarta")
            updates = {"attention": target, "updated_at": now}
            if action != "attend":
                updates["state"] = "RESOLVED"
            elif alert.state == "OPEN":
                updates["state"] = "ACKNOWLEDGED"
            result = await self._publish(alert.model_copy(update=updates), action, reason.strip())
            if self.active_id == alert_id and result.state == "RESOLVED":
                self.active_id, self.ok_since = None, None
            return result

    async def recover_technical(self, now: float) -> None:
        async with self._lock:
            if self.active_id is not None:
                alert=self.history[self.active_id]
                result=alert.model_copy(update={"state":"RESOLVED","event":"auto_resolve","recovery_at":now,"updated_at":now})
                await self._publish(result,"technical_recovery")
                self.active_id,self.ok_since=None,None

    async def prune(self, now: float, days: int) -> None:
        async with self._lock:
            if self.repository is not None:
                await asyncio.to_thread(self.repository.prune, now, days)
            self.history = {key: alert for key, alert in self.history.items()
                            if alert.state != "RESOLVED" or alert.timestamp >= now - days * 86400}

    async def observe(self, assessment: Assessment | None, now: float) -> None:
        async with self._lock:
            if self.active_id is None:
                return
            alert = self.history[self.active_id]
            if now - alert.timestamp >= self.config.expire_seconds:
                await self._apply(alert, "expire", now)
                return
            if assessment is None or assessment.level != "ok" or "no_pose" in assessment.reasons:
                self.ok_since = None
            else:
                if self.ok_since is None:
                    self.ok_since = now
                if now - self.ok_since >= self.config.auto_resolve_seconds:
                    await self._apply(alert, "auto_resolve", now)

    async def expire(self, now: float) -> None:
        async with self._lock:
            if self.active_id is not None:
                alert = self.history[self.active_id]
                if now - alert.timestamp >= self.config.expire_seconds:
                    await self._apply(alert, "expire", now)

    async def set_vision(self, alert_id: str, text: str | None, error: str | None, now: float) -> None:
        async with self._lock:
            if alert_id in self.history:
                alert = self.history[alert_id]
                await self._publish(alert.model_copy(update={"vision": text, "vision_error": error,
                                                            "updated_at": now}))
