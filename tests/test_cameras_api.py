# API multicámara: CRUD, zonas y credenciales por cámara, frames etiquetados y alerta compartida.
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.config import CamerasConfig, RiskConfig
from backend.main import create_app
from backend.model_loader import StubPoseEstimator


def headers(settings):
    return {"Authorization": f"Bearer {settings.token}"}


def pair(client, settings, camera_id):
    code = client.post(f"/pairing/camera?camera_id={camera_id}", headers=headers(settings)).json()["code"]
    result = client.post("/camera/pair", json={"code": code})
    assert result.status_code == 200
    return result.json()


def app_with(settings, scenario="standing", clock=None, **updates):
    config = settings.model_copy(update=updates) if updates else settings
    kwargs = {"clock": clock} if clock else {}
    return create_app(config, estimator=StubPoseEstimator(scenario),
                      estimator_factory=lambda: StubPoseEstimator(scenario), **kwargs)


def test_camera_endpoints_require_token(settings):
    with TestClient(app_with(settings)) as client:
        for method, path in [("GET", "/cameras"), ("POST", "/cameras"), ("PATCH", "/cameras/cam-1"),
                             ("DELETE", "/cameras/cam-1")]:
            assert client.request(method, path).status_code == 401


def test_camera_crud_limits_and_protection_of_main_camera(settings):
    config = settings.model_copy(update={"cameras": CamerasConfig(max=2)})
    with TestClient(app_with(config)) as client:
        h = headers(config)
        listed = client.get("/cameras", headers=h).json()
        assert [row["id"] for row in listed] == ["cam-1"] and listed[0]["connected"] is False
        created = client.post("/cameras", headers=h, json={"name": "Pasillo"})
        assert created.status_code == 201 and created.json()["id"] == "cam-2"
        assert client.post("/cameras", headers=h, json={"name": "Extra"}).status_code == 409  # max=2
        assert client.post("/cameras", headers=h, json={"name": "x", "id": "bad id!"}).status_code == 422
        renamed = client.patch("/cameras/cam-2", headers=h, json={"name": "Sala"})
        assert renamed.json()["name"] == "Sala"
        assert client.patch("/cameras/missing", headers=h, json={"name": "x"}).status_code == 404
        assert "cam-2" in client.app.state.pipelines
        assert client.delete("/cameras/cam-1", headers=h).status_code == 409
        assert client.delete("/cameras/cam-2", headers=h).status_code == 200
        assert client.delete("/cameras/cam-2", headers=h).status_code == 404
        assert "cam-2" not in client.app.state.pipelines
        assert [row["id"] for row in client.get("/cameras", headers=h).json()] == ["cam-1"]


def test_cameras_survive_restart(tmp_path, settings):
    config = settings.model_copy(update={"storage": settings.storage.model_copy(update={"path": str(tmp_path / "v.db")})})
    with TestClient(app_with(config)) as client:
        assert client.post("/cameras", headers=headers(config), json={"name": "Sala"}).status_code == 201
    with TestClient(app_with(config)) as client:
        assert [row["id"] for row in client.get("/cameras", headers=headers(config)).json()] == ["cam-1", "cam-2"]
        assert set(client.app.state.pipelines) == {"cam-1", "cam-2"}


def test_zones_are_independent_per_camera(settings):
    with TestClient(app_with(settings)) as client:
        h = headers(settings)
        client.post("/cameras", headers=h, json={"name": "Sala"})
        bed = {"revision": 0, "zones": [{"id": "bed", "name": "Cama", "kind": "bed",
                                         "polygon": [[0, 0], [.2, 0], [.2, .2], [0, .2]]}]}
        assert client.put("/zones?camera_id=cam-2", headers=h, json=bed).status_code == 200
        assert client.get("/zones?camera_id=cam-2", headers=h).json()["zones"][0]["id"] == "bed"
        assert client.get("/zones", headers=h).json()["zones"] == []  # cam-1 intacta
        assert client.get("/zones?camera_id=ghost", headers=h).status_code == 404
        assert client.put("/zones?camera_id=ghost", headers=h, json=bed).status_code == 404


def test_pairing_code_binds_the_credential_to_its_camera(settings):
    with TestClient(app_with(settings)) as client:
        h = headers(settings)
        client.post("/cameras", headers=h, json={"name": "Sala"})
        assert client.post("/pairing/camera?camera_id=ghost", headers=h).status_code == 404
        second = pair(client, settings, "cam-2")
        main = pair(client, settings, "cam-1")
        assert second["camera_id"] == "cam-2" and main["camera_id"] == "cam-1"
        repository = client.app.state.repository
        assert repository.camera_authorized(second["token"]) == "cam-2"
        assert repository.camera_authorized(main["token"]) == "cam-1"
        # Revocar una cámara no afecta a la otra.
        assert client.delete("/camera/pair?camera_id=cam-2", headers=h).status_code == 200
        assert not repository.camera_authorized(second["token"])
        assert repository.camera_authorized(main["token"]) == "cam-1"
        assert client.delete("/camera/pair?camera_id=ghost", headers=h).status_code == 404


def test_credential_decides_camera_and_frames_are_tagged(settings, jpeg):
    with TestClient(app_with(settings)) as client, client.websocket_connect("/ws/dashboard") as dash:
        dash.send_json({"type": "auth", "token": settings.token})
        client.post("/cameras", headers=headers(settings), json={"name": "Sala"})
        token = pair(client, settings, "cam-2")["token"]
        assert dash.receive_json()["camera_id"] == "cam-1"  # estado inicial de la cámara principal
        with client.websocket_connect("/ws/ingest") as ingest:
            # El cliente intenta suplantar cam-1: la credencial manda.
            ingest.send_json({"type": "auth", "token": token, "camera_id": "cam-1"})
            ingest.send_bytes(jpeg)
            assert dash.receive_bytes() == b"\x05cam-2" + jpeg
            pose = dash.receive_json()
            assert pose["type"] == "pose" and pose["camera_id"] == "cam-2"
            assert "cam-2" in client.app.state.manager.producers
            assert "cam-1" not in client.app.state.manager.producers


def test_duplicate_producer_for_the_same_camera_is_rejected(settings):
    with TestClient(app_with(settings)) as client:
        with client.websocket_connect("/ws/ingest") as first:
            first.send_json({"type": "auth", "token": settings.token})
            with client.websocket_connect("/ws/ingest") as second:
                second.send_json({"type": "auth", "token": settings.token})
                with pytest.raises(WebSocketDisconnect) as error:
                    second.receive_json()
                assert error.value.code == 1008


def test_unknown_camera_for_admin_token_is_rejected(settings):
    with TestClient(app_with(settings)) as client, client.websocket_connect("/ws/ingest") as ws:
        ws.send_json({"type": "auth", "token": settings.token, "camera_id": "ghost"})
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code == 1008


def test_two_cameras_produce_one_fall_alert_with_both_sources(settings, jpeg):
    now = [1000.0]
    config = settings.model_copy(update={"risk": RiskConfig(immobile_seconds=0.4),
        "server": settings.server.model_copy(update={"tick_seconds": 60})})
    with TestClient(app_with(config, "fall", clock=lambda: now[0])) as client:
        client.post("/cameras", headers=headers(config), json={"name": "Sala"})
        with client.websocket_connect("/ws/ingest") as one, client.websocket_connect("/ws/ingest") as two:
            one.send_json({"type": "auth", "token": config.token, "flow_control": True})
            two.send_json({"type": "auth", "token": pair(client, config, "cam-2")["token"], "flow_control": True})
            for index in range(8):
                now[0] = 1000 + index * 0.2
                for ws in (one, two):
                    ws.send_bytes(jpeg)
                    assert ws.receive_json()["type"] == "processed"
            falls = [a for a in client.get("/alerts", headers=headers(config)).json() if a["kind"] == "fall"]
            assert len(falls) == 1
            assert set(falls[0]["sources"]) == {"cam-1", "cam-2"}


def test_adding_pairing_and_regenerating_another_camera_preserves_live_streams(settings, jpeg):
    with TestClient(app_with(settings)) as client:
        h = headers(settings)
        first = pair(client, settings, "cam-1")
        main_pipeline = client.app.state.pipelines["cam-1"]
        with client.websocket_connect("/ws/ingest") as one:
            one.send_json({"type": "auth", "token": first["token"], "flow_control": True})
            one.send_bytes(jpeg)
            assert one.receive_json()["type"] == "processed"
            assert client.post("/cameras", headers=h, json={"name": "Segundo celular"}).status_code == 201
            older = client.post("/pairing/camera?camera_id=cam-2", headers=h).json()["code"]
            newer = client.post("/pairing/camera?camera_id=cam-2", headers=h).json()["code"]
            assert client.post("/camera/pair", json={"code": older}).status_code == 403
            second = client.post("/camera/pair", json={"code": newer}).json()
            with client.websocket_connect("/ws/ingest") as two:
                two.send_json({"type": "auth", "token": second["token"], "flow_control": True})
                two.send_bytes(jpeg)
                assert two.receive_json()["type"] == "processed"
                # Generar un QR, incluso para la misma cámara, no revoca una conexión ya vinculada.
                client.post("/pairing/camera?camera_id=cam-1", headers=h)
                client.post("/pairing/camera?camera_id=cam-2", headers=h)
                for stream in (one, two):
                    stream.send_bytes(jpeg)
                    assert stream.receive_json()["type"] == "processed"
                assert client.app.state.pipelines["cam-1"] is main_pipeline
                repository = client.app.state.repository
                assert repository.camera_authorized(first["token"]) == "cam-1"
                assert repository.camera_authorized(second["token"]) == "cam-2"
                assert all(row["connected"] for row in client.get("/cameras", headers=h).json())
