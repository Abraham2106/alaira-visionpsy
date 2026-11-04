# Comprueba los simuladores y los errores explícitos al seleccionar conectores reales.
import asyncio

import pytest

from backend.config import Settings, load_settings
from backend.model_loader import ModelLoadError, StubPoseEstimator, load_pose_estimator, load_vision_model


def test_stubs_without_weights_or_network(settings, jpeg):
    pose = load_pose_estimator(settings).estimate(jpeg, 0)
    assert len(pose.landmarks) == 33
    answer = asyncio.run(load_vision_model(settings).ask(jpeg, "test"))
    assert "[stub]" in answer.text


def test_demo_is_deterministic_and_not_image_inference(jpeg):
    model = StubPoseEstimator("demo")
    assert model.estimate(jpeg, 100).landmarks[11].y == 0.25
    assert model.estimate(jpeg, 104).landmarks[11].y == 0.76
    assert model.estimate(jpeg, 115).landmarks[11].y == 0.25


@pytest.mark.parametrize("kind,name", [("vision", "qvac")])
def test_pending_real_backends_fail_clearly(settings, kind, name):
    raw = settings.model_dump()
    raw["models"][kind]["backend"] = name
    with pytest.raises(NotImplementedError):
        (load_pose_estimator if kind == "pose" else load_vision_model)(Settings(**raw))


def test_mediapipe_requires_a_local_model(settings, tmp_path):
    raw = settings.model_dump()
    raw["models"]["pose"].update(backend="mediapipe", model_path=str(tmp_path / "missing.task"))
    with pytest.raises(ModelLoadError, match="modelo MediaPipe"):
        load_pose_estimator(Settings(**raw))


def test_llamacpp_missing_weights_and_existing_unconnected_weights(settings, tmp_path):
    raw = settings.model_dump()
    path = tmp_path / "model.gguf"
    raw["models"]["vision"].update(backend="llamacpp", gguf_path=str(path))
    with pytest.raises(ModelLoadError, match="GGUF"):
        load_vision_model(Settings(**raw))
    path.write_bytes(b"synthetic")
    with pytest.raises(NotImplementedError):
        load_vision_model(Settings(**raw))


@pytest.mark.parametrize("kind", ["pose", "vision"])
def test_unknown_backend_is_actionable(settings, kind):
    raw = settings.model_dump()
    raw["models"][kind]["backend"] = "missing"
    with pytest.raises(ModelLoadError, match="Backend desconocido"):
        (load_pose_estimator if kind == "pose" else load_vision_model)(Settings(**raw))


def test_settings_require_token_and_resolve_relative_weights(monkeypatch, tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("models:\n  vision:\n    gguf_path: model.gguf\n    mmproj_path: projector.gguf\n    executable: llama-server.exe\n    runtime_library_dirs: [cuda/bin]\n", encoding="utf-8")
    monkeypatch.setenv("APP_TOKEN", "")
    with pytest.raises(ValueError):
        load_settings(config)
    monkeypatch.setenv("APP_TOKEN", "synthetic-test-token")
    settings = load_settings(config)
    assert settings.models.vision.gguf_path == str(tmp_path / "model.gguf")
    assert settings.models.vision.mmproj_path == str(tmp_path / "projector.gguf")
    assert settings.models.vision.executable == str(tmp_path / "llama-server.exe")
    assert settings.models.vision.runtime_library_dirs == [str(tmp_path / "cuda" / "bin")]
    assert settings.models.pose.model_path == str((tmp_path.parent / "models" / "pose_landmarker_lite.task").resolve())
    assert "synthetic-test-token" not in repr(settings)


def test_settings_can_select_local_mediapipe_and_port(monkeypatch, tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("server:\n  port: 8000\nmodels:\n  pose:\n    backend: stub\n", encoding="utf-8")
    monkeypatch.setenv("APP_TOKEN", "synthetic-test-token")
    monkeypatch.setenv("POSE_BACKEND", "mediapipe")
    monkeypatch.setenv("APP_PORT", "8001")
    settings = load_settings(config)
    assert settings.models.pose.backend == "mediapipe"
    assert settings.server.port == 8001


@pytest.mark.parametrize("server", [{"allowed_origins": ["*"]}, {"host": "0.0.0.0"}, {"host": "8.8.8.8"}])
def test_public_bind_and_wildcard_cors_are_rejected(settings, server):
    with pytest.raises(ValueError):
        Settings(token=settings.token, server=server)


def test_visionpsy_registry_passes_configuration(settings, monkeypatch):
    pytest.importorskip("PIL")
    captured = {}
    def construct(**kwargs):
        captured.update(kwargs)
        return "adapter"
    monkeypatch.setattr("backend.visionpsy.VisionPsyModel", construct)
    raw = settings.model_dump()
    raw["models"]["vision"].update(backend="visionpsy", executable="local-server", port=8099, gpu_layers=0)
    assert load_vision_model(Settings(**raw)) == "adapter"
    assert captured["executable"] == "local-server" and captured["port"] == 8099
    assert captured["gpu_layers"] == 0 and captured["max_image_bytes"] == settings.server.max_frame_bytes
