import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.project_identity import ProjectResolutionError, ProjectResolver, canonicalize_path
from src.manifest import IndexManifest


def _write_identity_data(tmp_path, registry, projects):
    registry_path = tmp_path / "project_registry.json"
    manifest_path = tmp_path / "index_manifest.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    manifest_path.write_text(json.dumps({"projects": projects}), encoding="utf-8")
    return ProjectResolver(str(registry_path), str(manifest_path))


def test_resolve_project_returns_canonical_identity(tmp_path):
    root = tmp_path / "repo"
    child = root / "src" / "feature"
    child.mkdir(parents=True)
    resolver = _write_identity_data(
        tmp_path,
        {"repo": str(root)},
        {
            "repo": {
                "project_id": "stable-id",
                "path": str(root),
                "active_store": "store-1",
            }
        },
    )

    result = resolver.resolve(str(child))

    assert result.project_name == "repo"
    assert result.project_root == canonicalize_path(str(root))
    assert result.project_id == "stable-id"
    assert result.index_status == "ready"


def test_resolve_project_fails_closed_for_unknown_path(tmp_path):
    root = tmp_path / "repo"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()
    resolver = _write_identity_data(tmp_path, {"repo": str(root)}, {})

    with pytest.raises(ProjectResolutionError, match="No registered project") as error:
        resolver.resolve(str(other))

    assert error.value.code == "project_not_found"


def test_resolve_project_rejects_ambiguous_registry_entries(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    resolver = _write_identity_data(
        tmp_path,
        {"repo-a": str(root), "repo-b": str(root)},
        {},
    )

    with pytest.raises(ProjectResolutionError) as error:
        resolver.resolve(str(root))

    assert error.value.code == "ambiguous_project"
    assert len(error.value.candidates) == 2


def test_resolve_project_is_safe_for_parallel_reads(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    resolver = _write_identity_data(tmp_path, {"repo": str(root)}, {})

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: resolver.resolve(str(root)), range(32)))

    assert {item.project_name for item in results} == {"repo"}


def test_manifest_rejects_same_name_for_different_roots(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    manifest = IndexManifest(str(tmp_path / "state"))
    manifest.register_project("repo", str(first))

    with pytest.raises(ValueError, match="already registered"):
        manifest.register_project("repo", str(second))
