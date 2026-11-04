"""Los fallos técnicos no abren/cancelan caídas ni se confunden con atención."""
import asyncio

from backend.config import AlertConfig
from backend.model_loader import StubPoseEstimator, StubVisionModel
from backend.pipeline import Pipeline
from backend.storage import Repository


def test_camera_outage_is_deduplicated_and_recovers_separately(settings,sink,jpeg):
    async def run():
        repo=Repository()
        pipeline=Pipeline(settings,StubPoseEstimator(),StubVisionModel(),sink,repository=repo)
        await pipeline.process(jpeg,100)
        await pipeline.camera_disconnected(101)
        await pipeline.camera_disconnected(102)
        incidents=[a for a in repo.alerts() if a.kind=="technical"]
        assert len(incidents)==1
        incident=incidents[0]
        assert incident.state=="OPEN" and incident.attention=="pending"
        assert pipeline.alerts.active_id is None
        await pipeline.process(jpeg,103)
        recovered=repo.alert(incident.id)
        assert recovered.recovery_at==103 and recovered.state=="RESOLVED"
        assert recovered.attention=="pending"
        await pipeline.act(incident.id,"attend","",104)
        assert repo.alert(incident.id).attention=="attending"
        await pipeline.close()
        repo.close()
    asyncio.run(run())


def test_camera_loss_does_not_resolve_fall(settings,sink,jpeg):
    async def run():
        repo=Repository()
        pipeline=Pipeline(settings,StubPoseEstimator("fall"),StubVisionModel(),sink,repository=repo)
        for i in range(31):
            await pipeline.process(jpeg,100+i*.2)
        fall=[a for a in repo.alerts() if a.kind=="fall"][0]
        await pipeline.camera_disconnected(107)
        assert repo.alert(fall.id).state=="OPEN"
        assert len(repo.alerts())==2
        assert {item["kind"] for item in pipeline.snapshot()}=={"fall","technical"}
        await pipeline.close()
        repo.close()
    asyncio.run(run())


def test_no_camera_before_first_frame_is_not_an_outage(settings,sink):
    async def run():
        pipeline=Pipeline(settings,StubPoseEstimator(),StubVisionModel(),sink)
        await pipeline.camera_disconnected(100)
        assert pipeline.snapshot()==[]
        await pipeline.close()
    asyncio.run(run())
