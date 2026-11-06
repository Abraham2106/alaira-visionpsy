"""Configure Telegram at runtime; credentials stay in a private local file."""
import asyncio
import json
import os
from pathlib import Path
import re
import tempfile

from .notifications import TelegramClient, TelegramError


class TelegramSetup:
    def __init__(self, worker, repository, path: Path | None, fallback_token=""):
        self.worker, self.repository, self.path = worker, repository, path
        self.lock = asyncio.Lock()
        self.task = None
        self.record = {"token": fallback_token, "username": ""}
        if path is not None and path.exists():
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record, dict) or not all(isinstance(record.get(key), str) for key in ("token", "username")):
                    raise ValueError()
                self.record = record
            except (ValueError, OSError):
                self.record = {"token":"", "username":""}
                self.worker.last_error = "No se pudo leer el bot guardado. Vuelve a conectarlo."
        self.username = self.record.get("username", "")

    @property
    def enabled(self):
        return self.task is not None and not self.task.done()

    def save(self, record):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # NamedTemporaryFile is private (0600 on POSIX); replace atomically without touching .env.
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".telegram-", delete=False) as temporary:
                name = temporary.name
                json.dump(record, temporary)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(name, self.path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    async def start(self):
        token = self.record.get("token", "")
        if token:
            self.worker.client = TelegramClient(token)
            self.task = asyncio.create_task(self.worker.run())

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None

    async def connect(self, token):
        token = token.strip()
        if not re.fullmatch(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,100}", token):
            raise ValueError("Revisa el token que te dio BotFather.")
        async with self.lock:
            client = TelegramClient(token)
            identity = await client.call("getMe", {})
            if (not isinstance(identity, dict) or identity.get("is_bot") is not True
                    or not isinstance(identity.get("id"), int)
                    or not isinstance(identity.get("username"), str)
                    or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", identity.get("username", ""))):
                raise TelegramError("Telegram no devolvió un bot válido", retry=False)
            record = {"token": token, "username": identity["username"]}
            await asyncio.to_thread(self.save, record)
            await self.stop()
            self.repository.configure_telegram(identity["id"])
            self.record, self.username = record, identity["username"]
            self.worker.client = client
            self.worker.last_error = None
            self.task = asyncio.create_task(self.worker.run())

    async def disconnect(self):
        async with self.lock:
            record = {"token": "", "username": self.username}
            await asyncio.to_thread(self.save, record)
            await self.stop()
            self.record = record
            self.worker.last_error = None

    async def send_test(self, chat_id):
        async with self.lock:
            if not self.enabled:
                raise ValueError("Conecta el bot primero.")
            if not any(c["active"] and c["chat_id"] == chat_id for c in self.repository.contacts()):
                raise KeyError(chat_id)
            await self.worker.client.call("sendMessage", {
                "chat_id": chat_id,
                "text": "Prueba de VisionPsy: los avisos de esta PC están conectados. Este mensaje es una prueba; no indica una caída.",
            })
