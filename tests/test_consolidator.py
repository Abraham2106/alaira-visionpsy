# Consolidación de habitación: varias cámaras, una sola alerta de caída con sus fuentes.
import asyncio

from backend.alert_lifecycle import AlertStore
from backend.config import AlertConfig
from backend.consolidator import RoomConsolidator
from backend.risk import Assessment

CRITICAL = Assessment("critical", ("horizontal_torso", "immobile"))
OK = Assessment("ok", ())
NO_POSE = Assessment("ok", ("no_pose",))


def room(sink, stale=1.0, auto_resolve=3):
    return RoomConsolidator(AlertStore(AlertConfig(auto_resolve_seconds=auto_resolve), sink), stale_seconds=stale)


def test_two_cameras_share_one_alert_with_both_sources(sink):
    async def run():
        consolidator = room(sink)
        first = await consolidator.critical("cam-1", CRITICAL, 0)
        assert first is not None and first.sources == ["cam-1"]
        assert await consolidator.critical("cam-2", CRITICAL, 0.1) is None
        alerts = consolidator.snapshot()
        assert len(alerts) == 1 and alerts[0]["sources"] == ["cam-1", "cam-2"]
        # Repetir la misma fuente no duplica ni reabre.
        assert await consolidator.critical("cam-2", CRITICAL, 0.2) is None
        assert consolidator.snapshot()[0]["sources"] == ["cam-1", "cam-2"]
    asyncio.run(run())


def test_no_resolution_while_any_camera_is_still_critical(sink):
    async def run():
        consolidator = room(sink, stale=10)
        alert = await consolidator.critical("cam-1", CRITICAL, 0)
        for now in (0, 1, 2, 3, 4, 5, 6):
            await consolidator.observe("cam-1", OK, now)
            await consolidator.observe("cam-2", CRITICAL, now)
        assert consolidator.alerts.history[alert.id].state != "RESOLVED"
    asyncio.run(run())


def test_resolves_only_when_every_usable_camera_is_ok(sink):
    async def run():
        consolidator = room(sink, stale=10, auto_resolve=3)
        alert = await consolidator.critical("cam-1", CRITICAL, 0)
        for now in (1, 2, 3, 4, 5):
            await consolidator.observe("cam-1", OK, now)
            await consolidator.observe("cam-2", OK, now)
        assert consolidator.alerts.history[alert.id].state == "RESOLVED"
    asyncio.run(run())


def test_no_pose_camera_never_vetoes_resolution(sink):
    async def run():
        consolidator = room(sink, stale=10, auto_resolve=3)
        alert = await consolidator.critical("cam-1", CRITICAL, 0)
        for now in (1, 2, 3, 4, 5):
            await consolidator.observe("cam-1", OK, now)
            await consolidator.observe("cam-2", NO_POSE, now)
        assert consolidator.alerts.history[alert.id].state == "RESOLVED"
    asyncio.run(run())


def test_stale_or_disconnected_camera_never_vetoes_resolution(sink):
    async def run():
        consolidator = room(sink, stale=1.0, auto_resolve=3)
        alert = await consolidator.critical("cam-1", CRITICAL, 0)
        await consolidator.observe("cam-2", CRITICAL, 0)  # cam-2 deja de reportar
        for now in (3, 4, 5, 6, 7):
            await consolidator.observe("cam-1", OK, now)
        assert consolidator.alerts.history[alert.id].state == "RESOLVED"
        # Desconexión explícita: observe(None) retira el último resultado.
        consolidator2 = room(sink, stale=10, auto_resolve=3)
        second = await consolidator2.critical("cam-1", CRITICAL, 0)
        await consolidator2.observe("cam-2", CRITICAL, 0)
        await consolidator2.observe("cam-2", None, 1)
        for now in (2, 3, 4, 5, 6):
            await consolidator2.observe("cam-1", OK, now)
        assert consolidator2.alerts.history[second.id].state == "RESOLVED"
    asyncio.run(run())


def test_merged_assessment_levels(sink):
    consolidator = room(sink, stale=10)
    assert consolidator.merged(0) is None
    consolidator.latest["cam-1"] = (OK, 0)
    consolidator.latest["cam-2"] = (Assessment("suspect", ("fast_hip_drop",)), 0)
    assert consolidator.merged(0).level == "suspect"
    consolidator.latest["cam-1"] = (CRITICAL, 0)
    merged = consolidator.merged(0)
    assert merged.level == "critical" and set(merged.reasons) == {"horizontal_torso", "immobile", "fast_hip_drop"}
    assert consolidator.merged(100) is None  # todas obsoletas
