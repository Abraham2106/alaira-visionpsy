import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.notifications import NotificationWorker, TelegramClient, TelegramError
from backend.config import StorageConfig

TOKEN = "123456789:" + "x" * 35


@pytest.fixture
def telegram(monkeypatch):
    calls = []
    state = {"id":123456789,"username":"VisionPsyTestBot","error":False}
    async def call(self, method, payload):
        calls.append((method, payload))
        if state["error"]:
            raise TelegramError("Telegram HTTP 401", retry=False)
        if method == "getMe":
            return {"id":state["id"],"is_bot":True,"username":state["username"]}
        return {"message_id":1}
    async def idle(self):
        await asyncio.Event().wait()
    monkeypatch.setattr(TelegramClient,"call",call)
    monkeypatch.setattr(NotificationWorker,"run",idle)
    return state,calls


def test_connect_validate_pair_test_and_disconnect_without_restart(settings,telegram):
    state,calls=telegram
    headers={"Authorization":"Bearer "+settings.token}
    with TestClient(create_app(settings)) as client:
        assert client.post("/telegram",json={"token":TOKEN}).status_code==401
        assert client.post("/telegram/test/1").status_code==401
        assert client.delete("/telegram").status_code==401
        assert calls==[]
        response=client.post("/telegram",headers=headers,json={"token":TOKEN})
        assert response.status_code==200 and response.json()["bot_username"]=="VisionPsyTestBot"
        assert TOKEN not in response.text
        status=client.get("/notifications",headers=headers)
        assert status.json()["enabled"] and TOKEN not in status.text
        assert client.post("/telegram/test/99",headers=headers).status_code==404
        code=client.post("/pairing/telegram",headers=headers).json()["code"]
        asyncio.run(client.app.state.notifier.handle_update({"message":{"chat":{"id":1,"type":"private"},"text":"/start "+code}}))
        assert client.get("/contacts",headers=headers).json()[0]["active"]==1
        response=client.post("/telegram/test/1",headers=headers)
        assert response.status_code==200
        assert calls[-1][0]=="sendMessage" and "prueba" in calls[-1][1]["text"]
        assert client.get("/alerts",headers=headers).json()==[]
        client.delete("/telegram",headers=headers)
        assert not client.get("/notifications",headers=headers).json()["enabled"]
        assert client.post("/telegram/test/1",headers=headers).status_code==409


def test_rejected_token_does_not_replace_working_bot_or_echo_secrets(settings,telegram):
    state,calls=telegram
    headers={"Authorization":"Bearer "+settings.token}
    with TestClient(create_app(settings)) as client:
        assert client.post("/telegram",headers=headers,json={"token":TOKEN}).status_code==200
        state["error"]=True
        for payload in ({"token":TOKEN},{"token":"invalid-secret"},{"token":{"raw":TOKEN}}):
            response=client.post("/telegram",headers=headers,json=payload)
            assert response.status_code in (400,422,502)
            assert TOKEN not in response.text and "invalid-secret" not in response.text
        assert client.app.state.telegram.enabled
        assert client.app.state.telegram.record["token"]==TOKEN


def test_persistence_and_bot_identity_isolation(settings,tmp_path,telegram):
    state,calls=telegram
    config=settings.model_copy(update={"storage":StorageConfig(path=str(tmp_path/"session.db"))})
    headers={"Authorization":"Bearer "+settings.token}
    with TestClient(create_app(config)) as client:
        assert client.post("/telegram",headers=headers,json={"token":TOKEN}).status_code==200
        repo=client.app.state.repository
        repo.add_contact("1","Principal")
        repo.set_meta("telegram_offset",555)
        code=repo.issue_code("telegram",100)["code"]
        assert client.post("/telegram",headers=headers,json={"token":TOKEN}).status_code==200
        assert repo.contacts()[0]["active"]==1 and repo.meta("telegram_offset")=="555"
        assert repo.consume_code(code,"telegram",101)
    saved=tmp_path/"session.telegram.json"
    assert json.loads(saved.read_text())["token"]==TOKEN
    with TestClient(create_app(config)) as client:
        assert client.get("/notifications",headers=headers).json()["enabled"]
        state["id"]=987654321
        state["username"]="AnotherVisionBot"
        assert client.post("/telegram",headers=headers,json={"token":"987654321:"+"y"*35}).status_code==200
        repo=client.app.state.repository
        assert repo.contacts()[0]["active"]==0
        assert repo.meta("telegram_offset")=="0"
        assert client.delete("/telegram",headers=headers).status_code==200
    with TestClient(create_app(config)) as client:
        assert not client.get("/notifications",headers=headers).json()["enabled"]
    assert TOKEN not in saved.read_text()


def test_save_failure_keeps_current_bot(settings,telegram,monkeypatch):
    headers={"Authorization":"Bearer "+settings.token}
    with TestClient(create_app(settings)) as client:
        assert client.post("/telegram",headers=headers,json={"token":TOKEN}).status_code==200
        def failure(record):
            raise OSError("private path")
        monkeypatch.setattr(client.app.state.telegram,"save",failure)
        response=client.post("/telegram",headers=headers,json={"token":TOKEN})
        assert response.status_code==500 and "private path" not in response.text
        assert client.app.state.telegram.enabled
