import hashlib
import json
import os
import tempfile
import uuid

from src.embedding.base import EmbeddingProfile


class IndexManifest:
    schema_version = 2

    def __init__(self, state_directory: str):
        self.state_directory = os.path.abspath(state_directory)
        self.path = os.path.join(self.state_directory, "index_manifest.json")
        self.data = self._load()

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {"schema_version": self.schema_version, "projects": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError):
            return {"schema_version": self.schema_version, "projects": {}}
        if data.get("schema_version") != self.schema_version:
            return {"schema_version": self.schema_version, "projects": {}}
        data.setdefault("projects", {})
        return data

    def save(self) -> None:
        os.makedirs(self.state_directory, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix="index_manifest_", suffix=".json", dir=self.state_directory
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(self.data, file, indent=2, sort_keys=True)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def register_project(self, project_name: str, project_path: str) -> dict:
        canonical_path = os.path.normcase(os.path.realpath(project_path))
        project = self.data["projects"].get(project_name)
        if project and project["path"] != canonical_path:
            raise ValueError(
                f"Project name '{project_name}' is already registered for "
                f"'{project['path']}', not '{canonical_path}'. Use a unique project name."
            )
        if not project:
            project_id = hashlib.sha256(
                f"{project_name}\0{canonical_path}".encode("utf-8")
            ).hexdigest()[:12]
            project = {
                "project_id": project_id,
                "path": canonical_path,
                "active_store": None,
                "pending_store": None,
                "stores": {},
            }
            self.data["projects"][project_name] = project
            self.save()
        return project

    def get_project(self, project_name: str) -> dict | None:
        return self.data["projects"].get(project_name)

    @staticmethod
    def active_store(project: dict) -> dict | None:
        store_id = project.get("active_store")
        return project.get("stores", {}).get(store_id) if store_id else None

    @staticmethod
    def pending_store(project: dict) -> dict | None:
        store_id = project.get("pending_store")
        return project.get("stores", {}).get(store_id) if store_id else None

    def begin_store(self, project: dict, profile: EmbeddingProfile) -> dict:
        pending = self.pending_store(project)
        if pending and pending.get("profile") == profile.to_dict():
            return pending
        store_id = f"{profile.profile_id}_{uuid.uuid4().hex[:8]}"
        store = {
            "store_id": store_id,
            "profile": profile.to_dict(),
            "files": {},
            "complete": False,
        }
        project["stores"][store_id] = store
        project["pending_store"] = store_id
        self.save()
        return store

    def complete_store(self, project: dict, store: dict) -> str | None:
        previous = project.get("active_store")
        store["complete"] = True
        project["active_store"] = store["store_id"]
        project["pending_store"] = None
        self.save()
        return previous

    def remove_store(self, project: dict, store_id: str) -> None:
        project.get("stores", {}).pop(store_id, None)
        self.save()
