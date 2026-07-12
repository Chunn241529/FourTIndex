import json

import pytest

from src.database import Database


def registry_database():
    return object.__new__(Database)


def test_project_registry_is_created_and_replaced_atomically(tmp_path, monkeypatch):
    registry_path = tmp_path / "state" / "project_registry.json"
    monkeypatch.setattr(
        "src.database.os.path.expanduser", lambda _path: str(registry_path)
    )
    database = registry_database()
    database.save_project_path("demo", str(tmp_path / "demo"))

    data = json.loads(registry_path.read_text(encoding="utf-8"))
    assert data["demo"].endswith("/demo")
    assert database.get_project_path("demo") == data["demo"]


def test_project_registry_rejects_invalid_json(tmp_path, monkeypatch):
    registry_path = tmp_path / "project_registry.json"
    registry_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(
        "src.database.os.path.expanduser", lambda _path: str(registry_path)
    )
    database = registry_database()

    with pytest.raises(RuntimeError, match="Unable to read project registry"):
        database.save_project_path("demo", str(tmp_path))
    with pytest.raises(RuntimeError, match="Unable to read project registry"):
        database.get_project_path("demo")


def test_project_registry_surfaces_replace_failure(tmp_path, monkeypatch):
    registry_path = tmp_path / "project_registry.json"
    monkeypatch.setattr(
        "src.database.os.path.expanduser", lambda _path: str(registry_path)
    )
    monkeypatch.setattr(
        "src.database.os.replace",
        lambda *_args: (_ for _ in ()).throw(PermissionError("denied")),
    )

    with pytest.raises(RuntimeError, match="Unable to write project registry"):
        registry_database().save_project_path("demo", str(tmp_path))
