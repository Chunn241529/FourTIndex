import math

import pytest

from src.config import Config
from src.embedding.base import EmbeddingProvider, ProviderError
from src.indexing_service import IndexOptions, IndexingService


class FakeProvider(EmbeddingProvider):
    name = "fake"
    max_batch_items = 64

    def __init__(self):
        super().__init__("fake-code", 3)

    @staticmethod
    def _vector(text: str) -> list[float]:
        return [float(len(text)), float(sum(map(ord, text)) % 997), 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.request_count += 1
        return self._validate([self._vector(text) for text in texts], len(texts))

    def embed_query(self, text: str) -> list[float]:
        self.request_count += 1
        return self._vector(text)


def _config(tmp_path) -> Config:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  name: test-project",
                "  exclude_dirs: [.git, .fourtindex]",
                "  supported_extensions: [.py]",
                "database:",
                f"  persist_directory: '{(tmp_path / 'state' / 'db').as_posix()}'",
                "embedding:",
                "  provider_chain: [ollama]",
                "indexing:",
                "  parse_workers: 2",
                "  commit_batch_files: 32",
                "  max_file_size_bytes: 2097152",
                "  respect_gitignore: true",
            ]
        ),
        encoding="utf-8",
    )
    return Config(str(config_path))


def test_index_is_profile_pinned_incremental_and_removes_deleted_files(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (project / "b.py").write_text("def beta():\n    return 2\n", encoding="utf-8")
    (project / "ignored.py").write_text("def ignored():\n    return 0\n", encoding="utf-8")
    (project / ".gitignore").write_text("ignored.py\n", encoding="utf-8")

    service = IndexingService(_config(tmp_path))
    provider = FakeProvider()
    monkeypatch.setattr(
        service.embedding, "select_for_new_index", lambda requested="auto": provider
    )

    first = service.index_project(str(project), "test-project")
    assert first.indexed == 2
    assert first.chunks > 0
    assert first.completed
    assert first.requests == 1

    monkeypatch.setattr(
        service.embedding,
        "load_profile",
        lambda profile: setattr(service.embedding, "provider", provider) or provider,
    )
    request_count = provider.request_count
    second = service.index_project(str(project), "test-project")
    assert second.indexed == 0
    assert second.skipped == 2
    assert provider.request_count == request_count

    (project / "b.py").unlink()
    third = service.index_project(str(project), "test-project")
    assert third.removed == 1

    active = service.manifest.active_store(service.manifest.get_project("test-project"))
    assert set(active["files"]) == {"a.py"}

    with pytest.raises(ProviderError, match="requires --rebuild"):
        service.index_project(
            str(project),
            "test-project",
            options=IndexOptions(embedding_provider="remote"),
        )


def test_fake_vectors_are_finite():
    assert all(math.isfinite(value) for value in FakeProvider._vector("code"))
