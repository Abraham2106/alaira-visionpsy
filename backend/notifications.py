"""Telegram saliente y polling; nunca recibe ni transmite imágenes."""
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .messages import AlertMsg


class TelegramError(RuntimeError):
    def __init__(self, message, *, retry=True):
        super().__init__(message)
        self.retry = retry


class TelegramClient:
    def __init__(self, token):
        self._token = token

    async def call(self, method, payload):
        def request():
            req = Request(f"https://api.telegram.org/bot{self._token}/{method}",
                          data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
            try:
                with urlopen(req, timeout=12) as response:
                    result=json.load(response)
                if not isinstance(result, dict) or not result.get("ok") or "result" not in result:
                    raise TelegramError("Telegram rechazó la solicitud")
                return result["result"]
            except HTTPError as error:
                # No incluir URL ni token al propagar errores del cliente HTTP.
                raise TelegramError(f"Telegram HTTP {error.code}", retry=error.code not in {400,401,403,404}) from None
            except (URLError, TimeoutError, ValueError, OSError):
                raise TelegramError("No se pudo confirmar la operación de Telegram") from None
        return await asyncio.to_thread(request)


def message_text(alert, room, kind):
    heading = "Aviso al contacto de respaldo: evento sin atención" if kind == "escalation" else "Recordatorio: evento sin atención" if kind == "reminder" else "Monitoreo interrumpido" if alert.kind=="technical" else "Posible caída"
    when = datetime.fromtimestamp(alert.timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    detail="La cámara dejó de enviar imágenes. Comprueba la conexión." if alert.kind=="technical" else "Señales de postura e inmovilidad. Comprueba la situación."
    return f"{heading}\n{room}\n{when}\n{detail}\nID: {alert.id}"


class NotificationWorker:
    def __init__(self, repository, alerts, config, client=None, clock=time.time):
        self.repository, self.alerts, self.config = repository, alerts, config
        self.client = client or TelegramClient(os.getenv("TELEGRAM_BOT_TOKEN", ""))
        self.clock = clock
        self.last_error = None

    async def deliver_once(self):
        now=self.clock()
        await asyncio.to_thread(self.repository.reminders, now, self.config.reminder_seconds)
        for item in await asyncio.to_thread(self.repository.pending, now):
            # Releer antes de cada envío: un callback o revocación puede cancelar el lote.
            item=await asyncio.to_thread(self.repository.pending_item,item["id"],self.clock())
            if item is None:
                continue
            alert=AlertMsg.model_validate_json(item["payload"])
            # Recuperación o atención pueden llegar mientras el aviso estaba en cola.
            if alert.attention != "pending" or alert.state != "OPEN":
                continue
            payload={"chat_id":item["chat_id"],"text":message_text(alert,self.config.room_alias,item["kind"]),
                "reply_markup":{"inline_keyboard":[[
                    {"text":"Estoy atendiendo","callback_data":f"attend:{alert.id}"},
                    {"text":"Descartar","callback_data":f"discard:{alert.id}"}]]}}
            try:
                response=await self.client.call("sendMessage",payload)
                if not isinstance(response,dict) or "message_id" not in response:
                    raise TelegramError("Telegram devolvió una respuesta incompleta")
                await asyncio.to_thread(self.repository.delivery,item["id"],message_id=response["message_id"],now=now)
                self.last_error=None
            except TelegramError as error:
                self.last_error=str(error)
                await asyncio.to_thread(self.repository.delivery,item["id"],error=self.last_error,now=now,retry=error.retry)

    async def handle_update(self, update):
        callback=update.get("callback_query")
        if callback:
            # Una pulsación se autoriza por identidad del remitente y chat privado vinculado.
            message=callback.get("message",{})
            chat=message.get("chat",{})
            chat_id=str(chat.get("id",""))
            sender=str(callback.get("from",{}).get("id",""))
            authorized=chat.get("type")=="private" and sender==chat_id and any(
                c["active"] and c["chat_id"]==chat_id for c in self.repository.contacts())
            action, _, event_id = callback.get("data","").partition(":")
            text="Acción no autorizada o evento no disponible"
            if authorized and action in {"attend","discard"}:
                try:
                    await self.alerts.act(event_id,action,"Descartado por familiar en Telegram" if action=="discard" else "",self.clock())
                    text="Atención registrada" if action=="attend" else "Descarte registrado"
                except (KeyError,ValueError,RuntimeError):
                    text="El evento ya cambió o no está disponible"
            await self.client.call("answerCallbackQuery",{"callback_query_id":callback["id"],"text":text})
            return
        message=update.get("message",{})
        chat=message.get("chat",{})
        text=message.get("text","")
        if chat.get("type")=="private" and text.startswith("/start "):
            code=text.split(maxsplit=1)[1]
            for purpose, role in (("telegram","primary"),("telegram_backup","backup")):
                if self.repository.consume_code(code,purpose,self.clock()):
                    self.repository.add_contact(str(chat["id"]),"Familiar vinculado",role)
                    detail="como respaldo si nadie atiende" if role=="backup" else "como contacto principal"
                    await self.client.call("sendMessage",{"chat_id":chat["id"],"text":f"Vinculación confirmada {detail}. Recibirás avisos de texto de VisionPsy. El video permanece local."})
                    break

    async def poll_once(self):
        offset=int(self.repository.meta("telegram_offset"))
        updates=await self.client.call("getUpdates",{"offset":offset,"timeout":5,"allowed_updates":["message","callback_query"]})
        if not isinstance(updates,list) or any(not isinstance(u,dict) or not isinstance(u.get("update_id"),int) for u in updates):
            raise TelegramError("Telegram devolvió actualizaciones inválidas")
        for update in updates:
            await self.handle_update(update)
            self.repository.set_meta("telegram_offset",int(update["update_id"])+1)

    async def run(self):
        while True:
            try:
                await self.deliver_once()
                await self.poll_once()
            except TelegramError as error:
                self.last_error=str(error)
            await asyncio.sleep(1)
