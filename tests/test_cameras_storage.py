# Cámaras múltiples en SQLite: migración idempotente, credenciales y zonas por cámara.
import sqlite3

import pytest

from backend.domain import Zone, ZonesDocument
from backend.storage import Repository, RevisionConflict

ZONE = Zone(id="bed", name="Cama", kind="bed", polygon=[(0.1, 0.1), (0.5, 0.1), (0.5, 0.5)])


def test_default_camera_exists_and_migration_is_idempotent(tmp_path):
    path = tmp_path / "db.sqlite3"
    first = Repository(path)
    assert [c["id"] for c in first.cameras()] == ["cam-1"]
    first.close()
    second = Repository(path)
    assert [c["id"] for c in second.cameras()] == ["cam-1"]


def test_legacy_singleton_zones_and_credentials_migrate(tmp_path):
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE zones(singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL);
        CREATE TABLE credentials(digest TEXT PRIMARY KEY, created REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
    """)
    saved = ZonesDocument(revision=3, zones=[ZONE])
    db.execute("INSERT INTO zones VALUES(1,?)", (saved.model_dump_json(),))
    db.execute("INSERT INTO credentials VALUES(?,?,0)", (Repository.digest("legacy"), 1))
    db.commit()
    db.close()
    repo = Repository(path)
    assert repo.zones("cam-1") == saved
    assert repo.camera_authorized("legacy") == "cam-1"
    assert repo.zones("cam-2") == ZonesDocument()


def test_credentials_are_per_camera_and_revocation_is_isolated():
    repo = Repository()
    repo.add_camera("cam-2", "Pasillo", 10)
    one = repo.camera_credential(1, "cam-1")
    two = repo.camera_credential(2, "cam-2")
    assert repo.camera_authorized(one) == "cam-1"
    assert repo.camera_authorized(two) == "cam-2"
    repo.revoke_camera("cam-2")
    assert repo.camera_authorized(one) == "cam-1"
    assert repo.camera_authorized(two) is None
    again = repo.camera_credential(3, "cam-1")
    assert repo.camera_authorized(one) is None and repo.camera_authorized(again) == "cam-1"
    with pytest.raises(KeyError):
        repo.camera_credential(4, "cam-9")


def test_zones_are_independent_per_camera_with_revisions():
    repo = Repository()
    repo.add_camera("cam-2", "Pasillo")
    saved = repo.replace_zones(ZonesDocument(zones=[ZONE]), "cam-2")
    assert saved.revision == 1
    assert repo.zones("cam-1").zones == []
    with pytest.raises(RevisionConflict):
        repo.replace_zones(ZonesDocument(), "cam-2")


def test_camera_crud_validates_and_protects_default():
    repo = Repository()
    with pytest.raises(ValueError):
        repo.add_camera("../x", "Mala")
    with pytest.raises(ValueError):
        repo.add_camera("cam-2", "  ")
    repo.add_camera("cam-2", "Pasillo")
    with pytest.raises(ValueError):
        repo.add_camera("cam-2", "Otra")
    assert repo.rename_camera("cam-2", "Cocina")["name"] == "Cocina"
    token = repo.camera_credential(1, "cam-2")
    repo.remove_camera("cam-2")
    assert repo.camera_authorized(token) is None
    with pytest.raises(ValueError):
        repo.remove_camera("cam-1")
    with pytest.raises(KeyError):
        repo.remove_camera("cam-2")


def test_pairing_codes_are_isolated_by_camera_purpose():
    repo = Repository()
    a = repo.issue_code("camera:cam-1", 100)["code"]
    b = repo.issue_code("camera:cam-2", 100)["code"]
    assert repo.consume_code(a, "camera:cam-1", 101)
    assert not repo.consume_code(b, "camera:cam-1", 101)
    assert repo.consume_code(b, "camera:cam-2", 101)
