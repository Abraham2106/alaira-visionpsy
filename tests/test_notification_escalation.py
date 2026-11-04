import asyncio
import sqlite3

from backend.alert_lifecycle import AlertStore
from backend.config import AlertConfig, NotificationConfig
from backend.messages import AlertMsg
from backend.notifications import NotificationWorker, TelegramError
from backend.storage import Repository


def test_backup_pairing_is_private_scoped_expiring_and_single_use(sink):
    async def run():
        repo = Repository()
        calls = []
        class Client:
            async def call(self, method, payload):
                calls.append(payload)
                return {"message_id": 1}
        worker = NotificationWorker(repo, AlertStore(AlertConfig(),sink,repo), NotificationConfig(), Client(), clock=lambda:100)
        code = repo.issue_code("telegram_backup", 100, ttl=10)["code"]
        def update(chat, kind="private", value=code):
            return {"message":{"chat":{"id":chat,"type":kind},"text":"/start " + value}}
        await worker.handle_update(update("1", "group"))
        assert repo.contacts() == []
        assert not repo.consume_code(code, "camera", 101)
        await worker.handle_update(update("1"))
        await worker.handle_update(update("2"))
        assert repo.contacts() == [{"chat_id":"1","alias":"Familiar vinculado","active":1,"role":"backup"}]
        assert len(calls) == 1
        expired = repo.issue_code("telegram_backup", 100, ttl=10)["code"]
        worker.clock = lambda:110
        await worker.handle_update(update("3", value=expired))
        assert len(repo.contacts()) == 1
        repo.close()
    asyncio.run(run())


def test_existing_contacts_migrate_without_losing_identity(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE contacts(chat_id TEXT PRIMARY KEY, alias TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)")
        db.execute("INSERT INTO contacts VALUES('1','Original',1)")
    repo = Repository(path)
    assert repo.contacts() == [{"chat_id": "1", "alias": "Original", "active": 1, "role": "primary"}]
    repo.close()


def test_backup_gets_one_escalation_and_attention_cancels_pending(sink):
    async def run():
        repo = Repository()
        repo.add_contact("1", "Principal")
        repo.add_contact("2", "Respaldo", "backup")
        alert = AlertMsg(id="event", timestamp=100, updated_at=100, level="critical", reasons=["immobile"], state="OPEN")
        repo.save_alert(alert)
        assert [(i["chat_id"], i["kind"]) for i in repo.pending(100)] == [("1", "initial")]
        calls = []
        class Client:
            async def call(self, method, payload):
                calls.append(payload)
                return {"message_id": len(calls)}
        store = AlertStore(AlertConfig(), sink, repo)
        worker = NotificationWorker(repo, store, NotificationConfig(), Client(), clock=lambda: 100)
        await worker.deliver_once()
        worker.clock = lambda: 160
        await worker.deliver_once()
        await worker.deliver_once()
        assert [p["chat_id"] for p in calls] == ["1", "1", "2"]
        assert "respaldo" in calls[-1]["text"]
        assert len(repo.deliveries()) == 3
        # Un segundo evento atendido antes del vencimiento no escala.
        await store.act("event", "close", "", 161)
        repo.save_alert(alert.model_copy(update={"id": "next", "timestamp": 170}))
        await store.act("next", "attend", "", 171)
        worker.clock = lambda: 240
        await worker.deliver_once()
        assert len(calls) == 3
        repo.close()
    asyncio.run(run())


def test_permanent_provider_error_stops_retry_and_batch_rechecks_revocation(sink):
    async def run():
        repo = Repository()
        repo.add_contact("1", "A")
        repo.add_contact("2", "B")
        repo.save_alert(AlertMsg(id="event",timestamp=100,updated_at=100,level="critical",reasons=[],state="OPEN"))
        calls = []
        class Client:
            async def call(self, method, payload):
                calls.append(payload)
                repo.revoke_contact("2")
                raise TelegramError("Telegram HTTP 403", retry=False)
        worker = NotificationWorker(repo, AlertStore(AlertConfig(),sink,repo), NotificationConfig(), Client(), clock=lambda:101)
        await worker.deliver_once()
        await worker.deliver_once()
        assert len(calls) == 1
        assert {i["status"] for i in repo.deliveries()} == {"failed", "cancelled"}
        repo.close()
    asyncio.run(run())
