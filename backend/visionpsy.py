"""Persistent local VisionPsy-Nano Flash adapter backed by QVAC's patched llama.cpp.

The server owns the loaded GGUFs. JPEG bytes are sent in-memory to its loopback
OpenAI-compatible endpoint and are never written to disk by this adapter.
"""

from __future__ import annotations

import asyncio
import base64
import json
from io import BytesIO
import os
from pathlib import Path
import socket
import secrets
import subprocess
import time
from typing import Any

import httpx
from PIL import Image, UnidentifiedImageError

from .interfaces import VisionAnswer


class VisionPsyError(RuntimeError):
    """Base class for adapter and local runtime failures."""


class VisionPsyBusyError(VisionPsyError):
    """An inference is already running or the single inference slot is reserved."""


class VisionPsyTimeoutError(VisionPsyError, TimeoutError):
    """The request exceeded its deadline; the runtime may still be finishing it."""


class VisionPsyRuntimeError(VisionPsyError):
    """The local runtime failed or returned an invalid response."""


class VisionPsyModel:
    """Own one persistent local llama-server process and one inference slot."""

    def __init__(
        self,
        *,
        executable: str | Path,
        model_path: str | Path,
        mmproj_path: str | Path,
        timeout_seconds: float = 15.0,
        startup_timeout_seconds: float = 90.0,
        max_tokens: int = 128,
        max_image_bytes: int = 2_000_000,
        max_question_chars: int = 2_000,
        host: str = "127.0.0.1",
        port: int = 8089,
        threads: int = max(1, min(os.cpu_count() or 1, 8)),
        gpu_layers: int = 99,
        runtime_library_dirs: tuple[str | Path, ...] = (),
        shutdown_timeout_seconds: float = 3.0,
    ) -> None:
        self.executable = Path(executable).expanduser().resolve()
        self.model_path = Path(model_path).expanduser().resolve()
        self.mmproj_path = Path(mmproj_path).expanduser().resolve()
        for label, path in (("runtime", self.executable), ("model", self.model_path), ("projector", self.mmproj_path)):
            if not path.is_file():
                raise ValueError(f"No se encuentra el archivo de {label}: {path}")
        if not self.executable.name.lower().startswith("llama-server"):
            raise ValueError("El ejecutable debe ser llama-server del fork parcheado de QVAC")
        if not 1 <= port <= 65535 or not (host == "127.0.0.1" or host == "::1" or host == "localhost"):
            raise ValueError("El runtime debe escuchar en loopback y en un puerto válido")
        if timeout_seconds <= 0 or startup_timeout_seconds <= 0 or shutdown_timeout_seconds <= 0:
            raise ValueError("Los timeouts deben ser mayores que cero")
        if max_tokens < 1 or max_tokens > 512 or max_image_bytes < 4 or max_question_chars < 1 or threads < 1:
            raise ValueError("Límites de recursos inválidos")
        if not 0 <= gpu_layers <= 99:
            raise ValueError("gpu_layers debe estar entre 0 y 99")

        self.timeout_seconds = timeout_seconds
        self.startup_timeout_seconds = startup_timeout_seconds
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self.max_tokens = max_tokens
        self.max_image_bytes = max_image_bytes
        self.max_question_chars = max_question_chars
        self.host = host
        self.port = port
        self.threads = threads
        self.gpu_layers = gpu_layers
        self.runtime_library_dirs = tuple(Path(path).expanduser().resolve() for path in runtime_library_dirs)
        self._base_url = f"http://{'[' + host + ']' if ':' in host else host}:{port}"
        self._api_key = secrets.token_urlsafe(32)
        # Keep the slot until the server responds; ask() has its own caller deadline.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10, connect=2.0, read=None), trust_env=False,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        self._process: asyncio.subprocess.Process | None = None
        self._active: asyncio.Task[VisionAnswer] | None = None
        self._start_lock = asyncio.Lock()
        self._closing = False
        self._closed = False

    async def start(self) -> None:
        """Start the persistent server once and wait for its health endpoint."""
        async with self._start_lock:
            if self._closed or self._closing:
                raise VisionPsyRuntimeError("El adaptador está cerrado")
            if self._process is not None:
                if self._process.returncode is not None:
                    raise VisionPsyRuntimeError(f"llama-server terminó con código {self._process.returncode}")
                return
            if _port_in_use(self.host, self.port):
                raise VisionPsyRuntimeError(f"El puerto local {self.port} ya está ocupado")
            command = [
                str(self.executable), "-m", str(self.model_path), "--mmproj", str(self.mmproj_path),
                "--host", self.host, "--port", str(self.port), "--parallel", "1",
                "--n-gpu-layers", str(self.gpu_layers), "--threads", str(self.threads), "--ctx-size", "2048",
                "--no-webui",
                "--api-key", self._api_key,
            ]
            try:
                environment = os.environ.copy()
                environment["MTMD_NO_UPSCALE"] = "1"
                if self.runtime_library_dirs:
                    missing_dirs = [str(path) for path in self.runtime_library_dirs if not path.is_dir()]
                    if missing_dirs:
                        raise VisionPsyRuntimeError(f"No se encuentran bibliotecas del runtime: {', '.join(missing_dirs)}")
                    environment["PATH"] = os.pathsep.join(
                        [*(str(path) for path in self.runtime_library_dirs), environment.get("PATH", "")]
                    )
                self._process = await asyncio.create_subprocess_exec(
                    *command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    env=environment,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except OSError as error:
                raise VisionPsyRuntimeError(f"No se pudo iniciar llama-server: {error}") from error

            deadline = time.monotonic() + self.startup_timeout_seconds
            while time.monotonic() < deadline:
                if self._process.returncode is not None:
                    raise VisionPsyRuntimeError(f"llama-server terminó al iniciar (código {self._process.returncode})")
                try:
                    response = await self._client.get(f"{self._base_url}/health", timeout=1.0)
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.2)
            await self._stop_process()
            raise VisionPsyTimeoutError("llama-server no estuvo listo antes del timeout de inicio")

    async def ask(self, jpeg: bytes, question: str) -> VisionAnswer:
        """Ask about one JPEG; calls fail fast while the single slot is occupied."""
        if self._closed or self._closing:
            raise VisionPsyRuntimeError("El adaptador está cerrado")
        if self._process is None:
            raise VisionPsyRuntimeError("Llama primero a start() para cargar una vez el modelo")
        if self._process.returncode is not None:
            raise VisionPsyRuntimeError(f"llama-server terminó con código {self._process.returncode}")
        if self._active is not None and not self._active.done():
            raise VisionPsyBusyError("VisionPsy ya está procesando una imagen")
        question = _validate_question(question, self.max_question_chars)

        async def validated_request() -> VisionAnswer:
            await asyncio.to_thread(_validate_jpeg, jpeg, self.max_image_bytes)
            return await self._request(jpeg, question)

        task = asyncio.create_task(validated_request())
        self._active = task
        task.add_done_callback(self._clear_active)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=self.timeout_seconds)
        except TimeoutError as error:
            raise VisionPsyTimeoutError(
                "La inferencia excedió el timeout; el cupo sigue reservado hasta que termine el runtime"
            ) from error

    async def _request(self, jpeg: bytes, question: str) -> VisionAnswer:
        encoded = base64.b64encode(jpeg).decode("ascii")
        payload = {
            "model": "visionpsy-nano-flash",
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
            ]}],
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "stream": False,
        }
        try:
            response = await self._client.post(f"{self._base_url}/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            answer = _response_text(data)
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError, TypeError) as error:
            raise VisionPsyRuntimeError(f"Falló la inferencia local: {error}") from error
        return VisionAnswer(answer)

    def _clear_active(self, task: asyncio.Task[VisionAnswer]) -> None:
        if not task.cancelled():
            task.exception()  # Retrieve failures even after the caller timed out or cancelled.
        if self._active is task:
            self._active = None

    async def aclose(self) -> None:
        """Stop accepting calls, finish the outstanding request, then stop the server."""
        if self._closed:
            return
        self._closing = True
        active = self._active
        if active is not None and not active.done():
            try:
                await asyncio.wait_for(asyncio.shield(active), timeout=self.shutdown_timeout_seconds)
            except Exception:
                active.cancel()
                await asyncio.gather(active, return_exceptions=True)
        await self._stop_process()
        await self._client.aclose()
        self._closed = True

    async def _stop_process(self) -> None:
        process, self._process = self._process, None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=self.shutdown_timeout_seconds)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def __aenter__(self) -> "VisionPsyModel":
        try:
            await self.start()
        except BaseException:
            await self.aclose()
            raise
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()


def _validate_jpeg(jpeg: bytes, max_bytes: int) -> None:
    if not isinstance(jpeg, bytes) or len(jpeg) < 4 or len(jpeg) > max_bytes:
        raise ValueError(f"JPEG inválido o fuera del límite de {max_bytes} bytes")
    try:
        with Image.open(BytesIO(jpeg)) as image:
            if image.format != "JPEG" or image.width < 1 or image.height < 1 or image.width * image.height > 40_000_000:
                raise ValueError("Se requiere un JPEG válido de hasta 40 megapíxeles")
            image.verify()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("Los bytes recibidos no son un JPEG válido") from error


def _validate_question(question: str, max_chars: int) -> str:
    if not isinstance(question, str):
        raise ValueError("La pregunta debe ser texto")
    question = question.strip()
    if not question or len(question) > max_chars:
        raise ValueError(f"La pregunta debe tener entre 1 y {max_chars} caracteres")
    return question


def _response_text(data: Any) -> str:
    choices = data["choices"]
    if not isinstance(choices, list) or not choices:
        raise ValueError("La respuesta no contiene choices")
    content = choices[0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise ValueError("El runtime devolvió una respuesta vacía o malformada")
    return content.strip()


def _port_in_use(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((host, port)) == 0
