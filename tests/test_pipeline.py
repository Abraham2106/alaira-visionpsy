# Comprueba la integración sin transporte: una sola consulta visual, desconexión y errores.
import asyncio

import pytest

from backend.config import PipelineConfig, RiskConfig, Settings
from backend.interfaces import VisionAnswer
from backend.model_loader import StubPoseEstimator, StubVisionModel
from backend.pipeline import InvalidFrame, Pipeline
from backend.risk import Assessment


def test_capacity_loss_cannot_resolve_event_and_recovers_at_supported_fps(settings,sink,jpeg):
    async def run():
        config=settings.model_copy(update={
            "pipeline":settings.pipeline.model_copy(update={"history_size":8}),
            "risk":settings.risk.model_copy(update={"immobile_seconds":1}),
            "alerts":settings.alerts.model_copy(update={"auto_resolve_seconds":.2})})
        pipeline=Pipeline(config,StubPoseEstimator("standing"),StubVisionModel(),sink)
        for i in range(8):
            await pipeline.process(jpeg,i/30)
        alert=await pipeline.alerts.open(Assessment("critical",("immobile",)),7/30)
        for i in range(8,40):
            await pipeline.process(jpeg,i/30)
        assert "insufficient_history" in pipeline.last_status.reasons
        assert pipeline.alerts.history[alert.id].state == "OPEN"
        for i in range(1,16):
            await pipeline.process(jpeg,1.3+i/5)
        assert "insufficient_history" not in pipeline.last_status.reasons
        assert pipeline.alerts.history[alert.id].state == "RESOLVED"
        await pipeline.close()
    asyncio.run(run())


def test_vision_does_not_block_frames_and_runs_once_per_alert(settings, sink, jpeg):
    async def run():
        gate = asyncio.Event()
        class DelayedVision:
            calls = 0
            async def ask(self, image, question):
                self.calls += 1
                assert image == jpeg and question
                await gate.wait()
                return VisionAnswer("synthetic confirmation")
        vision = DelayedVision()
        config = settings.model_copy(update={"risk": RiskConfig(immobile_seconds=0.4)})
        pipeline = Pipeline(config, StubPoseEstimator("fall"), vision, sink, clock=lambda: 2)
        for index in range(8):
            await asyncio.wait_for(pipeline.process(jpeg, index * 0.2), 2)
        alert = next(iter(pipeline.alerts.history.values()))
        await pipeline.alerts.acknowledge(alert.id, 1.5)
        assert len(sink.frames) == 8 and len(pipeline.alerts.history) == 1
        assert vision.calls == 1
        gate.set()
        await asyncio.gather(*pipeline._tasks)
        updated = pipeline.alerts.history[alert.id]
        assert updated.id == alert.id and updated.state == "ACKNOWLEDGED"
        assert updated.vision == "synthetic confirmation"
        await pipeline.close()
    asyncio.run(run())


def test_camera_stall_does_not_resolve_alert_or_reuse_old_pose(settings, sink, jpeg):
    async def run():
        config = settings.model_copy(update={"risk": RiskConfig(immobile_seconds=0.4)})
        pipeline = Pipeline(config, StubPoseEstimator("fall"), StubVisionModel(), sink)
        for index in range(4):
            await pipeline.process(jpeg, index * 0.2)
        await pipeline.tick(5)
        assert pipeline.last_status.camera == "disconnected" and not pipeline.history
        assert next(iter(pipeline.alerts.history.values())).state == "OPEN"
        await pipeline.process(jpeg, 6)
        assert pipeline.last_status.level == "suspect"
        await pipeline.tick(121)
        assert next(iter(pipeline.alerts.history.values())).event == "expire"
        await pipeline.close()
    asyncio.run(run())


@pytest.mark.parametrize("failure", [False, True])
def test_no_pose_and_estimator_failure_clear_previous_pose(settings, sink, jpeg, failure):
    class Estimator:
        def estimate(self, image, timestamp):
            if failure:
                raise RuntimeError("synthetic estimator failure")
            return None
    async def run():
        pipeline = Pipeline(settings, Estimator(), StubVisionModel(), sink)
        await pipeline.process(jpeg, 0)
        assert next(message for message in sink.messages if message["type"] == "pose")["landmarks"] is None
        assert bool(pipeline.last_status.model_error) == failure
        assert pipeline.alerts.snapshot() == []
        await pipeline.process(jpeg, .2)
        assert pipeline.last_status.diagnostics["fps"] == 5
        await pipeline.camera_disconnected(.3)
        assert pipeline.last_status.diagnostics["fps"] == 0
        await pipeline.close()
    asyncio.run(run())


@pytest.mark.parametrize("timeout", [False, True])
def test_vision_failure_is_attached_to_same_alert(settings, sink, jpeg, timeout):
    class BrokenVision:
        async def ask(self, image, question):
            if timeout:
                await asyncio.Event().wait()
            raise RuntimeError("synthetic vision failure")
    async def run():
        models = settings.models.model_copy(update={"vision": settings.models.vision.model_copy(update={"timeout_seconds": 0.01})})
        config = settings.model_copy(update={"risk": RiskConfig(immobile_seconds=0.2), "models": models})
        pipeline = Pipeline(config, StubPoseEstimator("fall"), BrokenVision(), sink)
        await pipeline.process(jpeg, 0)
        await pipeline.process(jpeg, 0.2)
        await asyncio.gather(*pipeline._tasks)
        alert = next(iter(pipeline.alerts.history.values()))
        assert alert.state == "OPEN" and alert.vision is None and alert.vision_error
        await pipeline.close()
    asyncio.run(run())


def test_history_keeps_a_time_window_independent_of_fps(settings, sink, jpeg):
    async def run():
        pipeline_config = settings.pipeline.model_copy(update={"history_seconds": 8, "history_size": 1024})
        config = settings.model_copy(update={"pipeline": pipeline_config})
        pipeline = Pipeline(config, StubPoseEstimator("standing"), StubVisionModel(), sink)
        for index in range(10 * 30 + 1):  # 10 s a 30 FPS, el doble de los 5 s de inmovilidad.
            await pipeline.process(jpeg, index / 30)
        span = pipeline.history[-1].timestamp - pipeline.history[0].timestamp
        assert span == pytest.approx(8)
        assert len(pipeline.history) == 8 * 30 + 1
        await pipeline.close()
    asyncio.run(run())


def test_history_has_a_hard_memory_cap(settings, sink, jpeg):
    async def run():
        pipeline_config = settings.pipeline.model_copy(update={"history_seconds": 30, "history_size": 64})
        config = settings.model_copy(update={"pipeline": pipeline_config})
        pipeline = Pipeline(config, StubPoseEstimator("standing"), StubVisionModel(), sink)
        for index in range(10 * 30 + 1):
            await pipeline.process(jpeg, index / 30)
        assert len(pipeline.history) == 64
        assert pipeline.history[-1].timestamp == pytest.approx(10)
        assert "insufficient_history" in pipeline.last_status.reasons
        await pipeline.close()
    asyncio.run(run())


def test_history_window_must_cover_immobility(settings):
    with pytest.raises(ValueError, match="history_seconds"):
        Settings(token=settings.token, pipeline=PipelineConfig(history_seconds=4),
                 risk=RiskConfig(immobile_seconds=5))


def test_invalid_frames_do_not_reach_models(settings, sink):
    async def run():
        pipeline = Pipeline(settings, StubPoseEstimator(), StubVisionModel(), sink)
        for frame in [b"not-jpeg", b"\xff\xd8" + b"x" * settings.server.max_frame_bytes + b"\xff\xd9"]:
            with pytest.raises(InvalidFrame):
                await pipeline.process(frame)
        assert not sink.frames
        await pipeline.close()
    asyncio.run(run())
