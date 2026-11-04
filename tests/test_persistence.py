"""Regresiones de reinicio, outbox transaccional, autorización y geometría editable."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.alert_lifecycle import AlertStore
from backend.config import AlertConfig, NotificationConfig
from backend.domain import Zone, ZonesDocument
from backend.main import create_app
from backend.messages import AlertMsg
from backend.notifications import NotificationWorker, TelegramError
from backend.risk import Assessment
from backend.storage import Repository, RevisionConflict


def event(**updates):
    return AlertMsg(id="test-event",timestamp=100,updated_at=100,level="critical",
                    reasons=["horizontal_torso","immobile"],state="OPEN").model_copy(update=updates)


def test_retention_removes_replayed_and_persisted_events(sink):
    async def run():
        repo = Repository()
        repo.save_alert(event(state="RESOLVED", attention="closed"))
        store = AlertStore(AlertConfig(), sink, repo)
        assert len(store.snapshot()) == 1
        await store.prune(100 + 8 * 86400, 7)
        assert store.snapshot() == [] and repo.alerts() == []
        with pytest.raises(KeyError):
            await store.act("test-event", "attend", "", 100 + 8 * 86400)
        repo.close()
    asyncio.run(run())


def test_restart_restores_active_event_and_attention(tmp_path, sink):
    path=tmp_path/"events.sqlite3"
    async def run():
        repo=Repository(path)
        alerts=AlertStore(AlertConfig(),sink,repo)
        alert=await alerts.open(Assessment("critical",("immobile",)),100)
        await alerts.act(alert.id,"attend","",101)
        repo.close()
        reopened=Repository(path)
        restored=AlertStore(AlertConfig(),sink,reopened)
        assert restored.active_id == alert.id
        assert restored.history[alert.id].attention == "attending"
        assert (await restored.act(alert.id,"attend","",102)).updated_at == 101
        assert len(reopened.event_actions(alert.id)) == 1
        reopened.close()
    asyncio.run(run())


def test_expiration_is_not_human_attention(sink):
    async def run():
        repo=Repository()
        store=AlertStore(AlertConfig(expire_seconds=10),sink,repo)
        alert=await store.open(Assessment("critical",()),100)
        await store.expire(110)
        expired=repo.alerts()[0]
        assert expired.attention == "expired"
        assert expired.recovery_at is None
        result=await store.act(alert.id,"attend","",111)
        assert result.attention == "attending" and result.event == "expire"
        repo.close()
    asyncio.run(run())


def test_event_and_outbox_survive_restart_without_duplicates(tmp_path):
    path=tmp_path/"events.db"
    repo=Repository(path)
    repo.add_contact("123","Test contact")
    repo.save_alert(event())
    repo.save_alert(event(updated_at=101))
    repo.close()
    reopened=Repository(path)
    pending=reopened.pending(110)
    assert len(pending) == 1
    assert pending[0]["attempts"] == 0
    reopened.delivery(pending[0]["id"],error="synthetic timeout",now=110)
    assert reopened.pending(111) == []
    retry=reopened.pending(115)[0]
    assert retry["attempts"] == 1
    reopened.delivery(retry["id"],message_id=7,now=115)
    assert reopened.pending(1000) == []
    assert reopened.deliveries()[0]["message_id"] == "7"
    assert "landmarks" not in pending[0]["payload"]
    reopened.close()


def test_zone_revision_and_geometry_persist(tmp_path):
    repo=Repository(tmp_path/"zones.db")
    zone=Zone(id="bed",name="Cama",kind="bed",polygon=[(.1,.1),(.8,.1),(.8,.8),(.1,.8)])
    saved=repo.replace_zones(ZonesDocument(zones=[zone]))
    assert saved.revision == 1
    with pytest.raises(RevisionConflict):
        repo.replace_zones(ZonesDocument())
    repo.close()
    reopened=Repository(tmp_path/"zones.db")
    assert reopened.zones() == saved
    reopened.close()


@pytest.mark.parametrize("polygon",[
    [(0,0),(.5,.5),(1,1)],
    [(0,0),(1,1),(0,1),(1,0)],
    [(0,0),(1,0),(1,0),(0,1)],
    [(0,0),(2,0),(0,1)],
    [(0,0),(1,0),(.5,0),(0,1)],
])
def test_invalid_zone_is_rejected(polygon):
    with pytest.raises(ValidationError):
        Zone(id="test",name="Test",polygon=polygon)


def test_codes_are_scoped_expire_and_are_single_use():
    repo=Repository()
    code=repo.issue_code("camera",100,ttl=5)["code"]
    assert not repo.consume_code(code,"telegram",101)
    assert repo.consume_code(code,"camera",101)
    assert not repo.consume_code(code,"camera",102)
    expired=repo.issue_code("camera",100,ttl=5)["code"]
    assert not repo.consume_code(expired,"camera",105)
    assert code not in repo.db.execute("SELECT digest FROM codes").fetchone()[0]
    token=repo.camera_credential(100)
    assert repo.camera_authorized(token)
    repo.revoke_camera()
    assert not repo.camera_authorized(token)
    repo.close()


class FakeTelegram:
    def __init__(self, fail=False):
        self.calls=[]
        self.fail=fail
    async def call(self,method,payload):
        self.calls.append((method,payload))
        if self.fail:
            raise TelegramError("synthetic timeout")
        return {"message_id":77} if method=="sendMessage" else True


def test_worker_only_sends_event_text_and_retries(sink):
    async def run():
        repo=Repository()
        repo.add_contact("123","Familiar")
        repo.save_alert(event())
        fake=FakeTelegram(fail=True)
        worker=NotificationWorker(repo,AlertStore(AlertConfig(),sink,repo),NotificationConfig(),fake,clock=lambda:101)
        await worker.deliver_once()
        assert repo.deliveries()[0]["status"] == "pending"
        fake.fail=False
        worker.clock=lambda:106
        await worker.deliver_once()
        assert repo.deliveries()[0]["status"] == "sent"
        method,payload=fake.calls[-1]
        assert method == "sendMessage"
        assert set(payload) == {"chat_id","text","reply_markup"}
        assert "test-event" in payload["text"]
        assert "photo" not in json.dumps(payload) and "image" not in json.dumps(payload)
        repo.close()
    asyncio.run(run())


def test_callback_requires_linked_private_chat_and_is_idempotent(sink):
    async def run():
        repo=Repository()
        repo.add_contact("123","Familiar")
        repo.save_alert(event())
        store=AlertStore(AlertConfig(),sink,repo)
        worker=NotificationWorker(repo,store,NotificationConfig(),FakeTelegram(),clock=lambda:110)
        def update(sender="123",chat="123",kind="private"):
            return {"callback_query":{"id":"cb","from":{"id":sender},"data":"attend:test-event",
                    "message":{"chat":{"id":chat,"type":kind}}}}
        await worker.handle_update(update(sender="666"))
        await worker.handle_update(update(kind="group"))
        assert repo.alerts()[0].attention == "pending"
        await worker.handle_update(update())
        await worker.handle_update(update())
        assert repo.alerts()[0].attention == "attending"
        assert len(repo.event_actions("test-event")) == 1
        repo.close()
    asyncio.run(run())


def test_reminder_cancelled_on_attention_and_contact_revocation():
    repo=Repository()
    repo.add_contact("123","A")
    repo.add_contact("456","B")
    repo.save_alert(event())
    repo.reminders(200,60)
    repo.reminders(201,60)
    assert len(repo.pending(201)) == 4
    repo.save_alert(event(attention="attending"))
    assert len(repo.pending(202)) == 0
    repo.revoke_contact("123")
    assert len(repo.pending(202)) == 0
    repo.close()


def test_retention_keeps_recent_pending_but_removes_old_closed_events():
    repo=Repository()
    repo.add_contact("123","Familiar")
    repo.save_alert(event(state="RESOLVED",attention="closed"))
    repo.prune(6*86400,7)
    assert len(repo.alerts()) == 1
    repo.prune(10*86400,7)
    assert repo.alerts() == [] and repo.deliveries() == []
    repo.close()


def test_startup_applies_retention_before_replaying_history(settings,tmp_path):
    path=tmp_path/"retention.sqlite3"
    now=10*86400
    repo=Repository(path)
    repo.save_alert(event(id="old-closed",timestamp=100,state="RESOLVED",attention="closed"))
    repo.save_alert(event(id="recent-closed",timestamp=now-100,state="RESOLVED",attention="closed"))
    repo.save_alert(event(id="old-unresolved",timestamp=200))
    repo.close()
    config=settings.model_copy(update={"storage":settings.storage.model_copy(update={"path":str(path)})})
    with TestClient(create_app(config,clock=lambda:now)) as client:
        result=client.get("/alerts",headers={"Authorization":f"Bearer {settings.token}"}).json()
        assert {item["id"] for item in result}=={"recent-closed","old-unresolved"}
        assert {item["id"] for item in client.app.state.pipeline.snapshot()}=={"recent-closed","old-unresolved"}


def test_zones_api_is_authenticated_and_changes_pipeline(settings,tmp_path):
    config=settings.model_copy(update={"storage":settings.storage.model_copy(update={"path":str(tmp_path/"app.db")})})
    headers={"Authorization":f"Bearer {settings.token}"}
    with TestClient(create_app(config)) as client:
        assert client.get("/zones").status_code == 401
        document={"revision":0,"zones":[{"id":"bed","name":"Cama","kind":"bed","polygon":[[.1,.1],[.8,.1],[.8,.8]]}]}
        assert client.put("/zones",headers=headers,json=document).status_code == 200
        assert client.put("/zones",headers=headers,json=document).status_code == 409
        assert client.app.state.pipeline.settings.risk.safe_zones
    with TestClient(create_app(config)) as client:
        assert client.get("/zones",headers=headers).json()["revision"] == 1


def test_camera_credential_is_ingest_only_and_revocable(settings):
    headers={"Authorization":f"Bearer {settings.token}"}
    with TestClient(create_app(settings)) as client:
        code=client.post("/pairing/camera",headers=headers).json()["code"]
        result=client.post("/camera/pair",json={"code":code})
        assert result.status_code == 200
        token=result.json()["token"]
        assert client.get("/alerts",headers={"Authorization":f"Bearer {token}"}).status_code == 401
        assert client.post("/camera/pair",json={"code":code}).status_code == 403
        assert client.delete("/camera/pair",headers=headers).status_code == 200
        assert not client.app.state.repository.camera_authorized(token)


def test_camera_credential_cannot_read_or_modify_caregiver_resources(settings):
    headers={"Authorization":f"Bearer {settings.token}"}
    with TestClient(create_app(settings)) as client:
        code=client.post("/pairing/camera",headers=headers).json()["code"]
        token=client.post("/camera/pair",json={"code":code}).json()["token"]
        camera_headers={"Authorization":f"Bearer {token}"}
        for method,path,body in [
            ("GET","/zones",None),("PUT","/zones",{"revision":0,"zones":[]}),
            ("GET","/contacts",None),("DELETE","/contacts/123",None),
            ("GET","/notifications",None),("POST","/pairing/telegram",None),
            ("POST","/pairing/telegram_backup",None),("DELETE","/camera/pair",None),
            ("GET","/alerts/event/actions",None),("POST","/alerts/event/action",{"action":"attend"})]:
            assert client.request(method,path,headers=camera_headers,json=body).status_code==401,(method,path)
        assert client.app.state.repository.camera_authorized(token)
        assert client.get("/zones",headers=headers).json()=={"revision":0,"zones":[]}
