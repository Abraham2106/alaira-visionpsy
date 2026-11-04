# Verifica REST y WebSocket autenticados y el flujo completo mediante TestClient en memoria.
import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.config import RiskConfig
from backend.main import create_app
from backend.model_loader import StubPoseEstimator
from backend.ws_handler import ConnectionManager, authenticate as authenticate_socket


def auth(settings):
    return {"Authorization": f"Bearer {settings.token}"}


def authenticate(ws, settings):
    ws.send_json({"type": "auth", "token": settings.token})


@pytest.mark.parametrize("method,path", [("GET", "/health"), ("GET", "/alerts"), ("POST", "/alerts/missing/ack")])
def test_rest_requires_token(settings, method, path):
    with TestClient(create_app(settings)) as client:
        assert client.request(method, path).status_code == 401
        assert client.request(method, path, headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_health_history_missing_alert_and_cors(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/health", headers=auth(settings)).json()["name"] == "VisionPsy-Local"
        assert client.get("/alerts", headers=auth(settings)).json() == []
        assert client.post("/alerts/missing/ack", headers=auth(settings)).status_code == 404
        for origin, allowed in [("http://localhost:5173", True), ("https://untrusted.invalid", False)]:
            response = client.options("/alerts/a/ack", headers={"Origin": origin,
                "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Authorization"})
            assert (response.status_code == 200) == allowed
            assert ("access-control-allow-origin" in response.headers) == allowed


@pytest.mark.parametrize("path", ["/ws/dashboard", "/ws/ingest"])
@pytest.mark.parametrize("message", [{"type": "auth", "token": "invalid"}, {"type": "other"}, "bad-json"])
def test_ws_rejects_unauthenticated_messages(settings, path, message):
    with TestClient(create_app(settings)) as client, client.websocket_connect(path) as ws:
        if isinstance(message, str):
            ws.send_text(message)
        else:
            ws.send_json(message)
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code == 1008


def test_ws_checks_origin_and_auth_timeout(settings):
    config = settings.model_copy(update={"server": settings.server.model_copy(update={"auth_timeout_seconds": 0.01})})
    with TestClient(create_app(config)) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/dashboard", headers={"Origin": "https://untrusted.invalid"}):
                pass
        with client.websocket_connect("/ws/dashboard") as ws:
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_json()
            assert error.value.code == 1008


def test_ws_frame_pose_status_and_camera_disconnect(settings, jpeg):
    with TestClient(create_app(settings)) as client, client.websocket_connect("/ws/dashboard") as dash:
        authenticate(dash, settings)
        assert dash.receive_json()["camera"] == "waiting"
        with client.websocket_connect("/ws/ingest") as ingest:
            authenticate(ingest, settings)
            ingest.send_bytes(jpeg)
            assert dash.receive_bytes() == jpeg
            assert len(dash.receive_json()["landmarks"]) == 33
            assert dash.receive_json()["level"] == "ok"
        assert dash.receive_json()["landmarks"] is None
        assert dash.receive_json()["camera"] == "disconnected"


def test_alert_ack_vision_dedupe_auto_resolve_and_replay(settings, jpeg):
    now = [1000.0]
    config = settings.model_copy(update={"risk": RiskConfig(immobile_seconds=0.4),
        "server": settings.server.model_copy(update={"tick_seconds": 60})})
    estimator = StubPoseEstimator("fall")
    app = create_app(config, estimator=estimator, clock=lambda: now[0])
    with TestClient(app) as client, client.websocket_connect("/ws/dashboard") as dash:
        authenticate(dash, settings)
        dash.receive_json()
        with client.websocket_connect("/ws/ingest") as ingest:
            authenticate(ingest, settings)
            for index in range(4):
                now[0] = 1000 + index * 0.2
                ingest.send_bytes(jpeg)
                assert dash.receive_bytes() == jpeg
                assert dash.receive_json()["type"] == "pose"
                dash.receive_json()
                if index == 2:
                    opened = dash.receive_json()
                    updated = dash.receive_json()
                    assert opened["state"] == "OPEN" and opened["vision"] is None
                    assert updated["id"] == opened["id"] and "[stub]" in updated["vision"]
            alerts = client.get("/alerts", headers=auth(settings)).json()
            assert len(alerts) == 1
            alert_id = alerts[0]["id"]
            acknowledged = client.post(f"/alerts/{alert_id}/ack", headers=auth(settings))
            assert acknowledged.json()["state"] == "ACKNOWLEDGED"
            assert dash.receive_json()["state"] == "ACKNOWLEDGED"
            assert client.post(f"/alerts/{alert_id}/ack", headers=auth(settings)).status_code == 409
            estimator.scenario = "standing"
            for index in range(17):
                now[0] = 1000.8 + index * 0.2
                ingest.send_bytes(jpeg)
                dash.receive_bytes(); dash.receive_json(); dash.receive_json()
                if index == 15:
                    assert dash.receive_json()["state"] == "RESOLVED"
            assert client.get("/alerts", headers=auth(settings)).json()[0]["event"] == "auto_resolve"
        with client.websocket_connect("/ws/dashboard") as reconnected:
            authenticate(reconnected, settings)
            assert reconnected.receive_json()["type"] == "status"
            replay = reconnected.receive_json()
            assert replay["id"] == alert_id and replay["state"] == "RESOLVED"


def test_ws_rejects_invalid_binary_and_second_producer(settings, jpeg):
    with TestClient(create_app(settings)) as client, client.websocket_connect("/ws/dashboard") as dash:
        authenticate(dash, settings); dash.receive_json()
        with client.websocket_connect("/ws/ingest") as first:
            authenticate(first, settings); first.send_bytes(jpeg)
            dash.receive_bytes(); dash.receive_json(); dash.receive_json()
            with client.websocket_connect("/ws/ingest") as second:
                authenticate(second, settings)
                with pytest.raises(WebSocketDisconnect) as error:
                    second.receive_json()
                assert error.value.code == 1008
            first.send_bytes(b"invalid")
            with pytest.raises(WebSocketDisconnect) as error:
                first.receive_json()
            assert error.value.code == 1003


def test_dead_ws_client_does_not_stop_delivery_to_other_clients():
    class Client:
        def __init__(self, broken):
            self.broken, self.received = broken, []
        async def send_json(self, message):
            if self.broken:
                raise RuntimeError("synthetic disconnect")
            self.received.append(message)
        async def close(self, code):
            pass
    async def run():
        manager = ConnectionManager()
        dead, live = Client(True), Client(False)
        manager.clients.update([dead, live])
        await manager.emit({"type": "test"})
        assert dead not in manager.clients and live.received == [{"type": "test"}]
    asyncio.run(run())


@pytest.mark.parametrize("exception", [WebSocketDisconnect(1001), RuntimeError("socket already closed")])
def test_disconnect_during_authentication_does_not_close_twice(settings, exception):
    class ClosedSocket:
        headers = {}
        async def accept(self):
            pass
        async def receive_json(self):
            raise exception
        async def close(self, **kwargs):
            raise AssertionError("No debe cerrar de nuevo un socket desconectado")
    assert asyncio.run(authenticate_socket(ClosedSocket(), settings)) is False
