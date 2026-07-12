import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path


class ProjectResolutionError(ValueError):
    def __init__(self, code: str, message: str, candidates: list[dict] | None = None):
        super().__init__(message)
        self.code = code
        self.candidates = candidates or []

    def as_dict(self) -> dict:
        return {
            "success": False,
            "error": {"code": self.code, "message": str(self)},
            "candidates": self.candidates,
        }


def canonicalize_path(path: str) -> str:
    if not path or not str(path).strip():
        raise ProjectResolutionError("invalid_path", "workspace_path must not be empty")
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))


@dataclass(frozen=True)
class ProjectIdentity:
    project_name: str
    project_root: str
    project_id: str
    index_status: str

    def as_dict(self) -> dict:
        return {
            "success": True,
            "project_name": self.project_name,
            "project_root": self.project_root,
            "project_id": self.project_id,
            "index_status": self.index_status,
        }


class ProjectResolver:
    def __init__(self, registry_path: str, manifest_path: str):
        self.registry_path = Path(registry_path)
        self.manifest_path = Path(manifest_path)

    def list_identities(self) -> list[ProjectIdentity]:
        registry = self._load_json(self.registry_path, {})
        manifest = self._load_json(self.manifest_path, {"projects": {}})
        manifest_projects = manifest.get("projects", {})
        identities = []
        for project_name, project_path in registry.items():
            canonical_root = canonicalize_path(project_path)
            project = manifest_projects.get(project_name) or {}
            manifest_root = project.get("path")
            if manifest_root and canonicalize_path(manifest_root) != canonical_root:
                status = "path_mismatch"
            elif project.get("active_store"):
                status = "ready"
            elif project:
                status = "registered"
            else:
                status = "registry_only"
            project_id = project.get("project_id") or self._project_id(
                project_name, canonical_root
            )
            identities.append(
                ProjectIdentity(project_name, canonical_root, project_id, status)
            )
        return sorted(identities, key=lambda item: (item.project_name.casefold(), item.project_root))

    def resolve(self, workspace_path: str, project_name: str | None = None) -> ProjectIdentity:
        workspace = canonicalize_path(workspace_path)
        candidates = [
            identity
            for identity in self.list_identities()
            if self._contains(identity.project_root, workspace)
        ]
        if project_name is not None:
            candidates = [item for item in candidates if item.project_name == project_name]

        if not candidates:
            raise ProjectResolutionError(
                "project_not_found",
                f"No registered project contains workspace path: {workspace}",
            )

        deepest_length = max(len(item.project_root) for item in candidates)
        closest = [item for item in candidates if len(item.project_root) == deepest_length]
        unique = {(item.project_name, item.project_root) for item in closest}
        if len(unique) != 1:
            raise ProjectResolutionError(
                "ambiguous_project",
                f"Multiple projects match workspace path: {workspace}",
                [item.as_dict() for item in closest],
            )
        identity = closest[0]
        if identity.index_status == "path_mismatch":
            raise ProjectResolutionError(
                "project_path_mismatch",
                f"Registry and index manifest disagree for project '{identity.project_name}'",
                [identity.as_dict()],
            )
        return identity

    @staticmethod
    def _contains(root: str, path: str) -> bool:
        try:
            return os.path.commonpath([root, path]) == root
        except ValueError:
            return False

    @staticmethod
    def _project_id(project_name: str, canonical_root: str) -> str:
        return hashlib.sha256(
            f"{project_name}\0{canonical_root}".encode("utf-8")
        ).hexdigest()[:12]

    @staticmethod
    def _load_json(path: Path, default: dict) -> dict:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectResolutionError(
                "registry_unavailable", f"Cannot read project identity data at {path}: {exc}"
            ) from exc
        return data if isinstance(data, dict) else default
