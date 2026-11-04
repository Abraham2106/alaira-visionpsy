from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
Image = pytest.importorskip("PIL.Image")

from backend.visionpsy import (
    VisionPsyBusyError,
    VisionPsyModel,
    VisionPsyRuntimeError,
    VisionPsyTimeoutError,
    _response_text,
    _validate_jpeg,
)


def jpeg_bytes() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (12, 8), "white").save(out, format="JPEG")
    return out.getvalue()


class FakeClient:
    def __init__(self, handler=None):
        self.handler = handler or (lambda *args, **kwargs: _response())
        self.closed = False
        self.calls = []

    async def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return await self.handler(*args, **kwargs)

    async def aclose(self):
        self.closed = True


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


async def _response(text="A person is sitting."):
    return FakeResponse({"choices": [{"message": {"content": text}}]})


def model(tmp_path: Path, client: FakeClient | None = None) -> VisionPsyModel:
    executable = tmp_path / "llama-server.exe"
    executable.touch()
    lm = tmp_path / "model.gguf"
    lm.touch()
    mmproj = tmp_path / "mmproj.gguf"
    mmproj.touch()
    instance = VisionPsyModel(executable=executable, model_path=lm, mmproj_path=mmproj, timeout_seconds=1)
    instance._process = SimpleNamespace(returncode=None)
    if client is not None:
        instance._client = client
    return instance


def test_missing_runtime_or_weights_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="runtime"):
        VisionPsyModel(executable=tmp_path / "llama-server.exe", model_path="missing.gguf", mmproj_path="missing-mm.gguf")
    executable = tmp_path / "other.exe"
    executable.touch()
    model_path = tmp_path / "model.gguf"
    model_path.touch()
    mmproj = tmp_path / "mmproj.gguf"
    mmproj.touch()
    with pytest.raises(ValueError, match="llama-server"):
        VisionPsyModel(executable=executable, model_path=model_path, mmproj_path=mmproj)


def test_rejects_invalid_jpeg_and_question(tmp_path):
    instance = model(tmp_path)

    async def run():
        with pytest.raises(ValueError, match="JPEG"):
            await instance.ask(b"nope", "describe")
        with pytest.raises(ValueError, match="pregunta"):
            await instance.ask(jpeg_bytes(), "  ")

    asyncio.run(run())


def test_jpeg_size_and_content_limits():
    with pytest.raises(ValueError):
        _validate_jpeg(jpeg_bytes(), 10)
    with pytest.raises(ValueError, match="JPEG válido"):
        _validate_jpeg(b"\xff\xd8\xff\xd9", 100)


def test_ask_sends_bytes_as_in_memory_data_url_and_returns_vision_answer(tmp_path):
    client = FakeClient()
    instance = model(tmp_path, client)

    async def run():
        result = await instance.ask(jpeg_bytes(), "Describe la escena")
        assert result.text == "A person is sitting."
        payload = client.calls[0][1]["json"]
        assert payload["messages"][0]["content"][0]["text"] == "Describe la escena"
        assert payload["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert payload["max_tokens"] == 128

    asyncio.run(run())


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [{"message": {"content": " "}}]}, {"choices": [{"message": {}}]}])
def test_rejects_empty_or_malformed_runtime_output(payload):
    with pytest.raises((ValueError, KeyError)):
        _response_text(payload)


def test_runtime_http_errors_are_wrapped(tmp_path):
    async def failed(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    instance = model(tmp_path, FakeClient(failed))

    async def run():
        with pytest.raises(VisionPsyRuntimeError, match="inferencia local"):
            await instance.ask(jpeg_bytes(), "question")

    asyncio.run(run())


def test_concurrent_request_is_rejected_and_timeout_keeps_slot_reserved(tmp_path):
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed(*_args, **_kwargs):
        started.set()
        await release.wait()
        return await _response()

    instance = model(tmp_path, FakeClient(delayed))
    instance.timeout_seconds = 0.04

    async def run():
        first = asyncio.create_task(instance.ask(jpeg_bytes(), "first"))
        await started.wait()
        with pytest.raises(VisionPsyBusyError):
            await instance.ask(jpeg_bytes(), "second")
        with pytest.raises(VisionPsyTimeoutError):
            await first
        with pytest.raises(VisionPsyBusyError):
            await instance.ask(jpeg_bytes(), "third")
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert (await instance.ask(jpeg_bytes(), "fourth")).text

    asyncio.run(run())


def test_caller_cancellation_does_not_release_slot_early(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed(*_args, **_kwargs):
        started.set()
        await release.wait()
        return await _response()

    instance = model(tmp_path, FakeClient(delayed))

    async def run():
        caller = asyncio.create_task(instance.ask(jpeg_bytes(), "first"))
        await started.wait()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        with pytest.raises(VisionPsyBusyError):
            await instance.ask(jpeg_bytes(), "second")
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert (await instance.ask(jpeg_bytes(), "third")).text

    asyncio.run(run())


def test_async_request_does_not_block_event_loop(tmp_path):
    async def delayed(*_args, **_kwargs):
        await asyncio.sleep(0.02)
        return await _response()

    instance = model(tmp_path, FakeClient(delayed))

    async def run():
        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(5):
                await asyncio.sleep(0.003)
                ticks += 1

        answer, _ = await asyncio.gather(instance.ask(jpeg_bytes(), "question"), ticker())
        assert answer.text and ticks == 5

    asyncio.run(run())


def test_start_reuses_one_persistent_process(tmp_path, monkeypatch):
    instance = model(tmp_path)
    instance._process = None
    launches = []

    async def process(*args, **kwargs):
        launches.append((args, kwargs))
        return SimpleNamespace(returncode=None)

    class HealthClient(FakeClient):
        async def get(self, *_args, **_kwargs):
            return FakeResponse({})

    instance._client = HealthClient()
    monkeypatch.setattr("backend.visionpsy._port_in_use", lambda *_: False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", process)

    async def run():
        await instance.start()
        await instance.start()
        assert len(launches) == 1
        assert "--parallel" in launches[0][0]

    asyncio.run(run())


def test_close_releases_client_and_is_idempotent(tmp_path):
    client = FakeClient()
    instance = model(tmp_path, client)
    instance._process = None

    async def run():
        await instance.aclose()
        await instance.aclose()
        assert client.closed
        with pytest.raises(VisionPsyRuntimeError, match="cerrado"):
            await instance.ask(jpeg_bytes(), "question")

    asyncio.run(run())


def test_simultaneous_calls_reserve_slot_before_jpeg_validation(tmp_path, monkeypatch):
    import threading
    validating, release = threading.Event(), threading.Event()
    def validate(*_):
        validating.set()
        assert release.wait(2)
    monkeypatch.setattr("backend.visionpsy._validate_jpeg", validate)
    instance = model(tmp_path, FakeClient())
    async def run():
        first = asyncio.create_task(instance.ask(jpeg_bytes(), "first"))
        try:
            assert await asyncio.to_thread(validating.wait, 1)
            with pytest.raises(VisionPsyBusyError):
                await instance.ask(jpeg_bytes(), "second")
        finally:
            release.set()
        assert (await first).text
    asyncio.run(run())


def test_failed_context_start_closes_resources(tmp_path, monkeypatch):
    instance = model(tmp_path, FakeClient())
    instance._process = None
    async def failed_start():
        raise VisionPsyRuntimeError("synthetic startup failure")
    monkeypatch.setattr(instance, "start", failed_start)
    async def run():
        with pytest.raises(VisionPsyRuntimeError):
            async with instance:
                pytest.fail("Startup should fail")
        assert instance._closed and instance._client.closed
    asyncio.run(run())
