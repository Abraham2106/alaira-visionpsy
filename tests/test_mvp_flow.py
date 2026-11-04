"""Recorrido contractual: cámara vinculada → pose sintética → evento → bot simulado → reinicio."""
from fastapi.testclient import TestClient
import asyncio

from backend.config import AlertConfig, RiskConfig
from backend.main import create_app
from backend.model_loader import StubPoseEstimator


def test_paired_camera_event_delivery_attention_and_restart(settings,tmp_path,jpeg):
    now = [100.0]
    config = settings.model_copy(update={
        "storage":settings.storage.model_copy(update={"path":str(tmp_path/"mvp.sqlite3")}),
        "risk":RiskConfig(immobile_seconds=.4),
        "alerts":AlertConfig(expire_seconds=120)})
    headers={"Authorization":"Bearer " + config.token}
    calls=[]
    class Telegram:
        async def call(self,method,payload):
            calls.append((method,payload))
            return {"message_id":len(calls)}
    app=create_app(config,estimator=StubPoseEstimator("fall"),clock=lambda:now[0])
    with TestClient(app) as client:
        worker=app.state.notifier
        worker.client=Telegram()
        family=client.post("/pairing/telegram",headers=headers).json()["code"]
        # El worker de producción se mantiene apagado; este proveedor no usa red.
        client.portal.call(worker.handle_update,{"message":{"chat":{"id":123,"type":"private"},"text":"/start " + family}})
        camera=client.post("/pairing/camera",headers=headers).json()["code"]
        credential=client.post("/camera/pair",json={"code":camera}).json()["token"]
        assert client.get("/alerts",headers={"Authorization":"Bearer " + credential}).status_code == 401
        zones={"revision":0,"zones":[{"id":"bed","name":"Cama","kind":"bed","polygon":[[0,0],[.1,0],[.1,.1],[0,.1]]}]}
        assert client.put("/zones",headers=headers,json=zones).status_code == 200
        with client.websocket_connect("/ws/ingest") as ws:
            ws.send_json({"type":"auth","token":credential,"flow_control":True})
            for i in range(10):
                now[0]=100+i*.2
                ws.send_bytes(jpeg)
                assert ws.receive_json()["type"] == "processed"
            events=client.get("/alerts",headers=headers).json()
            fall=next(e for e in events if e["kind"]=="fall")
            client.portal.call(worker.deliver_once)
            delivered=[p for method,p in calls if method=="sendMessage" and fall["id"] in p["text"]]
            assert len(delivered)==1 and set(delivered[0])=={"chat_id","text","reply_markup"}
            client.portal.call(worker.handle_update,{"callback_query":{"id":"cb","from":{"id":123},"data":"attend:" + fall["id"],"message":{"chat":{"id":123,"type":"private"}}}})
            assert client.get("/alerts",headers=headers).json()[0]["attention"]=="attending"
            assert client.delete("/camera/pair",headers=headers).status_code==200
        saved_id=fall["id"]
    with TestClient(create_app(config,clock=lambda:now[0])) as client:
        assert client.get("/zones",headers=headers).json()["zones"][0]["id"]=="bed"
        restored=next(e for e in client.get("/alerts",headers=headers).json() if e["id"]==saved_id)
        assert restored["attention"]=="attending"
        assert client.get(f"/alerts/{saved_id}/actions",headers=headers).json()[0]["action"]=="attend"
        notices=client.get("/notifications",headers=headers).json()["deliveries"]
        assert any(d["event_id"]==saved_id and d["status"]=="sent" for d in notices)


def test_zone_change_resets_evidence_without_claiming_human_attention(settings,jpeg):
    now=[0.0]
    config=settings.model_copy(update={"risk":RiskConfig(immobile_seconds=.4)})
    headers={"Authorization":"Bearer " + config.token}
    app=create_app(config,estimator=StubPoseEstimator("fall"),clock=lambda:now[0])
    with TestClient(app) as client:
        pipeline=app.state.pipeline
        for i in range(6):
            now[0]=i*.2
            client.portal.call(pipeline.process,jpeg)
        original=client.get("/alerts",headers=headers).json()[0]
        assert original["state"]=="OPEN"
        zone={"revision":0,"zones":[{"id":"bed","name":"Cama","kind":"bed","polygon":[[.4,.6],[.9,.6],[.9,.95],[.4,.95]]}]}
        assert client.put("/zones",headers=headers,json=zone).status_code==200
        assert len(pipeline.history)==0 and pipeline.alerts.ok_since is None
        saved=client.get("/alerts",headers=headers).json()[0]
        assert saved["id"]==original["id"] and saved["attention"]=="pending" and saved["state"]=="OPEN"
        # Cerrar explícitamente antes de comprobar que la zona suprime un nuevo evento.
        client.post(f"/alerts/{original['id']}/action",headers=headers,json={"action":"close"})
        for i in range(6,12):
            now[0]=i*.2
            client.portal.call(pipeline.process,jpeg)
        assert pipeline.last_status.reasons==["safe_zone"]
        assert pipeline.alerts.active_id is None
        assert client.put("/zones",headers=headers,json={"revision":1,"zones":[]}).status_code==200
        now[0]=2.4
        client.portal.call(pipeline.process,jpeg)
        assert pipeline.last_status.level=="suspect" and pipeline.alerts.active_id is None
        for timestamp in (2.6,2.8,3.0):
            now[0]=timestamp
            client.portal.call(pipeline.process,jpeg)
        assert pipeline.alerts.active_id not in {None,original["id"]}
