import json

import pytest

from src import mcp_server
from src.project_identity import ProjectResolutionError, ProjectResolver


def test_detect_active_project_resolves_exact_and_descendant_paths(tmp_path, monkeypatch):
    project = tmp_path / "dynamic_monas"
    descendant = project / "src" / "components"
    descendant.mkdir(parents=True)
    registry = tmp_path / "project_registry.json"
    manifest = tmp_path / "index_manifest.json"
    registry.write_text(json.dumps({"dynamic_monas": str(project)}), encoding="utf-8")
    manifest.write_text(json.dumps({"projects": {}}), encoding="utf-8")
    monkeypatch.setattr(
        mcp_server,
        "project_resolver",
        ProjectResolver(str(registry), str(manifest)),
    )

    assert mcp_server.detect_active_project(str(project)) == "dynamic_monas"
    assert mcp_server.detect_active_project(str(descendant)) == "dynamic_monas"


def test_detect_active_project_fails_closed_when_unregistered(tmp_path, monkeypatch):
    registry = tmp_path / "project_registry.json"
    manifest = tmp_path / "index_manifest.json"
    registry.write_text("{}", encoding="utf-8")
    manifest.write_text(json.dumps({"projects": {}}), encoding="utf-8")
    monkeypatch.setattr(
        mcp_server,
        "project_resolver",
        ProjectResolver(str(registry), str(manifest)),
    )

    with pytest.raises(ProjectResolutionError) as error:
        mcp_server.detect_active_project(str(tmp_path / "unregistered"))

    assert error.value.code == "project_not_found"
