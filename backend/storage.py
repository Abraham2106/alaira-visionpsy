"""Repositorio SQLite: eventos, zonas, contactos y outbox en transacciones locales."""
import hashlib
import json
import re
import secrets
import sqlite3
import threading
from pathlib import Path

from .domain import ZonesDocument
from .messages import AlertMsg


class RevisionConflict(ValueError):
    pass


DEFAULT_CAMERA = "cam-1"
CAMERA_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def valid_camera_id(camera_id):
    return isinstance(camera_id, str) and CAMERA_ID.fullmatch(camera_id) is not None


class Repository:
    def __init__(self, path=":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                action TEXT NOT NULL, reason TEXT NOT NULL, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS zones(singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS contacts(chat_id TEXT PRIMARY KEY, alias TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                chat_id TEXT NOT NULL REFERENCES contacts(chat_id), kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL, message_id TEXT, error TEXT,
                UNIQUE(event_id,chat_id,kind));
            CREATE TABLE IF NOT EXISTS codes(digest TEXT PRIMARY KEY, purpose TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS credentials(digest TEXT PRIMARY KEY, created REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cameras(id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS camera_zones(camera_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)
        if "camera_id" not in {row["name"] for row in self.db.execute("PRAGMA table_info(credentials)")}:
            self.db.execute("ALTER TABLE credentials ADD COLUMN camera_id TEXT NOT NULL DEFAULT 'cam-1'")
        # Migración idempotente: la cámara por defecto siempre existe y hereda las zonas del singleton anterior.
        self.db.execute("INSERT OR IGNORE INTO cameras(id,name,created,active) VALUES(?,?,0,1)",(DEFAULT_CAMERA,"Cámara 1"))
        self.db.execute("INSERT OR IGNORE INTO camera_zones(camera_id,payload) SELECT ?,payload FROM zones WHERE singleton=1",(DEFAULT_CAMERA,))
        self.db.commit()
        if "role" not in {row["name"] for row in self.db.execute("PRAGMA table_info(contacts)")}:
            self.db.execute("ALTER TABLE contacts ADD COLUMN role TEXT NOT NULL DEFAULT 'primary'")
            self.db.commit()

    def close(self):
        with self.lock:
            self.db.close()

    def alerts(self, limit=100, kind=None):
        with self.lock:
            if kind is None:
                rows = self.db.execute("SELECT payload FROM events ORDER BY created DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = self.db.execute("SELECT payload FROM events WHERE COALESCE(json_extract(payload,'$.kind'),'fall')=? ORDER BY created DESC, rowid DESC LIMIT ?", (kind,limit)).fetchall()
            return [AlertMsg.model_validate_json(r["payload"]) for r in reversed(rows)]

    def alert(self, event_id):
        with self.lock:
            row=self.db.execute("SELECT payload FROM events WHERE id=?",(event_id,)).fetchone()
            if row is None:
                raise KeyError(event_id)
            return AlertMsg.model_validate_json(row[0])

    def save_alert(self, alert: AlertMsg, action=None, reason=""):
        with self.lock, self.db:
            new = self.db.execute("SELECT 1 FROM events WHERE id=?", (alert.id,)).fetchone() is None
            self.db.execute("INSERT INTO events VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                            (alert.id,alert.timestamp,alert.model_dump_json()))
            if action:
                self.db.execute("INSERT INTO actions(event_id,action,reason,at) VALUES(?,?,?,?)",(alert.id,action,reason,alert.updated_at))
            if new:
                self.db.execute("INSERT OR IGNORE INTO outbox(event_id,chat_id,kind,next_at) SELECT ?,chat_id,'initial',? FROM contacts WHERE active=1 AND role='primary'",
                                (alert.id,alert.timestamp))
            if alert.attention != "pending" or alert.event == "auto_resolve":
                self.db.execute("UPDATE outbox SET status='cancelled' WHERE event_id=? AND status='pending'",(alert.id,))

    def event_actions(self, event_id):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT action,reason,at FROM actions WHERE event_id=? ORDER BY id",(event_id,))]

    def zones(self, camera_id=DEFAULT_CAMERA):
        with self.lock:
            row=self.db.execute("SELECT payload FROM camera_zones WHERE camera_id=?",(camera_id,)).fetchone()
            return ZonesDocument.model_validate_json(row[0]) if row else ZonesDocument()

    def replace_zones(self, document, camera_id=DEFAULT_CAMERA):
        with self.lock, self.db:
            current=self.zones(camera_id)
            if current.revision != document.revision:
                raise RevisionConflict("Las zonas cambiaron. Recarga antes de guardar.")
            updated=document.model_copy(update={"revision":current.revision+1})
            self.db.execute("INSERT INTO camera_zones VALUES(?,?) ON CONFLICT(camera_id) DO UPDATE SET payload=excluded.payload",(camera_id,updated.model_dump_json()))
            return updated

    def cameras(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT id,name,created,active FROM cameras ORDER BY rowid")]

    def camera(self, camera_id):
        with self.lock:
            row=self.db.execute("SELECT id,name,created,active FROM cameras WHERE id=?",(camera_id,)).fetchone()
            return dict(row) if row else None

    def add_camera(self, camera_id, name, now=0):
        if not valid_camera_id(camera_id):
            raise ValueError("Identificador de cámara no válido")
        name=(name or "").strip()[:80]
        if not name:
            raise ValueError("Escribe un nombre para la cámara")
        with self.lock, self.db:
            if self.db.execute("SELECT 1 FROM cameras WHERE id=?",(camera_id,)).fetchone():
                raise ValueError("La cámara ya existe")
            self.db.execute("INSERT INTO cameras(id,name,created,active) VALUES(?,?,?,1)",(camera_id,name,now))
        return self.camera(camera_id)

    def rename_camera(self, camera_id, name):
        name=(name or "").strip()[:80]
        if not name:
            raise ValueError("Escribe un nombre para la cámara")
        with self.lock, self.db:
            if self.db.execute("UPDATE cameras SET name=? WHERE id=?",(name,camera_id)).rowcount != 1:
                raise KeyError(camera_id)
        return self.camera(camera_id)

    def remove_camera(self, camera_id):
        if camera_id == DEFAULT_CAMERA:
            raise ValueError("La cámara principal no se puede eliminar")
        with self.lock, self.db:
            if self.db.execute("DELETE FROM cameras WHERE id=?",(camera_id,)).rowcount != 1:
                raise KeyError(camera_id)
            self.db.execute("UPDATE credentials SET revoked=1 WHERE camera_id=?",(camera_id,))
            self.db.execute("DELETE FROM camera_zones WHERE camera_id=?",(camera_id,))
            self.db.execute("DELETE FROM codes WHERE purpose=?",(f"camera:{camera_id}",))

    def contacts(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT chat_id,alias,active,role FROM contacts ORDER BY rowid")]

    def add_contact(self, chat_id, alias, role="primary"):
        if role not in {"primary", "backup"}:
            raise ValueError("Rol de contacto desconocido")
        with self.lock, self.db:
            self.db.execute("UPDATE outbox SET status='cancelled' WHERE chat_id=? AND status='pending' AND EXISTS (SELECT 1 FROM contacts WHERE chat_id=? AND role!=?)",(str(chat_id),str(chat_id),role))
            self.db.execute("INSERT INTO contacts(chat_id,alias,active,role) VALUES(?,?,1,?) ON CONFLICT(chat_id) DO UPDATE SET alias=excluded.alias,active=1,role=excluded.role",(str(chat_id),alias[:80],role))

    def revoke_contact(self, chat_id):
        with self.lock, self.db:
            self.db.execute("UPDATE contacts SET active=0 WHERE chat_id=?",(str(chat_id),))
            self.db.execute("UPDATE outbox SET status='cancelled' WHERE chat_id=? AND status='pending'",(str(chat_id),))

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def issue_code(self, purpose, now, ttl=300):
        code=secrets.token_urlsafe(12)
        with self.lock, self.db:
            self.db.execute("DELETE FROM codes WHERE purpose=? OR expires<?",(purpose,now))
            self.db.execute("INSERT INTO codes VALUES(?,?,?,0)",(self.digest(code),purpose,now+ttl))
        return {"code":code,"expires_at":now+ttl}

    def consume_code(self, code, purpose, now):
        if not isinstance(code,str) or not 8 <= len(code) <= 100:
            return False
        with self.lock, self.db:
            result=self.db.execute("UPDATE codes SET used=1 WHERE digest=? AND purpose=? AND expires>? AND used=0",(self.digest(code),purpose,now))
            return result.rowcount == 1

    def camera_credential(self, now, camera_id=DEFAULT_CAMERA):
        token=secrets.token_urlsafe(32)
        with self.lock, self.db:
            if self.db.execute("SELECT 1 FROM cameras WHERE id=?",(camera_id,)).fetchone() is None:
                raise KeyError(camera_id)
            # Una credencial vigente por cámara: vincular de nuevo revoca solo la de esa cámara.
            self.db.execute("UPDATE credentials SET revoked=1 WHERE camera_id=?",(camera_id,))
            self.db.execute("INSERT INTO credentials(digest,created,revoked,camera_id) VALUES(?,?,0,?)",(self.digest(token),now,camera_id))
        return token

    def camera_authorized(self, token):
        """Devuelve el camera_id dueño de la credencial vigente, o None."""
        with self.lock:
            row=self.db.execute("SELECT c.camera_id FROM credentials c JOIN cameras m ON m.id=c.camera_id WHERE c.digest=? AND c.revoked=0 AND m.active=1",(self.digest(token),)).fetchone()
            return row[0] if row else None

    def revoke_camera(self, camera_id=None):
        with self.lock, self.db:
            if camera_id is None:
                self.db.execute("UPDATE credentials SET revoked=1")
            else:
                self.db.execute("UPDATE credentials SET revoked=1 WHERE camera_id=?",(camera_id,))

    def meta(self, key, default="0"):
        with self.lock:
            row=self.db.execute("SELECT value FROM meta WHERE key=?",(key,)).fetchone()
            return row[0] if row else default

    def set_meta(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,str(value)))

    def pending(self, now):
        with self.lock:
            return [dict(r) for r in self.db.execute("""SELECT o.*, e.payload FROM outbox o JOIN events e ON e.id=o.event_id
                JOIN contacts c ON c.chat_id=o.chat_id WHERE o.status='pending' AND o.next_at<=? AND c.active=1 ORDER BY o.id LIMIT 10""",(now,))]

    def pending_item(self, item_id, now):
        with self.lock:
            row=self.db.execute("""SELECT o.*, e.payload FROM outbox o JOIN events e ON e.id=o.event_id
                JOIN contacts c ON c.chat_id=o.chat_id WHERE o.id=? AND o.status='pending' AND o.next_at<=? AND c.active=1""",(item_id,now)).fetchone()
            return dict(row) if row else None

    def delivery(self, item_id, *, message_id=None, error=None, now=0, retry=True):
        with self.lock, self.db:
            if error:
                row=self.db.execute("SELECT attempts FROM outbox WHERE id=?",(item_id,)).fetchone()
                if row is not None:
                    delay=min(300,5*(2**min(row[0],6)))
                    self.db.execute("UPDATE outbox SET attempts=attempts+1,error=?,next_at=?,status=? WHERE id=? AND status='pending'",(error[:160],now+delay,"pending" if retry else "failed",item_id))
            else:
                self.db.execute("UPDATE outbox SET status='sent',attempts=attempts+1,message_id=?,error=NULL WHERE id=? AND status='pending'",(str(message_id),item_id))

    def deliveries(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT id,event_id,kind,status,attempts,next_at,message_id,error FROM outbox ORDER BY id DESC LIMIT 50")]

    def reminders(self, now, delay):
        with self.lock, self.db:
            for row in self.db.execute("SELECT id,payload FROM events WHERE created<=?",(now-delay,)).fetchall():
                alert=AlertMsg.model_validate_json(row["payload"])
                if alert.attention != "pending" or alert.state != "OPEN":
                    continue
                self.db.execute("INSERT OR IGNORE INTO outbox(event_id,chat_id,kind,next_at) SELECT ?,chat_id,CASE WHEN role='backup' THEN 'escalation' ELSE 'reminder' END,? FROM contacts WHERE active=1",(alert.id,now))

    def prune(self, now, days):
        with self.lock, self.db:
            # El plazo de retención limita también avisos antiguos; no enviar una alarma de hace semanas.
            self.db.execute("DELETE FROM events WHERE created<? AND json_extract(payload,'$.state')='RESOLVED'",(now-days*86400,))
            self.db.execute("DELETE FROM codes WHERE expires<?",(now,))
