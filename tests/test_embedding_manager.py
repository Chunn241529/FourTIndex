from types import SimpleNamespace

from src.config import Config
from src.embedding.manager import EmbeddingManager


class StubProvider:
    name = "lmstudio"

    def health_check(self):
        return None


def test_auto_selection_prefers_lmstudio(monkeypatch):
    requested = []

    def create_provider(name, _config):
        requested.append(name)
        return StubProvider()

    monkeypatch.setattr("src.embedding.manager.create_provider", create_provider)

    config = SimpleNamespace(embedding_provider_chain=["lmstudio", "ollama"])
    selected = EmbeddingManager(config).select_for_new_index("auto")

    assert selected.name == "lmstudio"
    assert requested == ["lmstudio"]


def test_provider_chain_uses_ollama_only_as_lmstudio_fallback(monkeypatch):
    monkeypatch.setenv("FOURTINDEX_EMBEDDING_PROVIDER_CHAIN", "remote,ollama")

    config = Config("missing-config.yaml")

    assert config.embedding_provider_chain == ["lmstudio", "ollama"]


def test_auto_selection_falls_back_to_ollama(monkeypatch):
    requested = []

    class Provider(StubProvider):
        def __init__(self, name):
            self.name = name

        def health_check(self):
            if self.name == "lmstudio":
                from src.embedding.base import ProviderUnavailableError

                raise ProviderUnavailableError("offline")

    def create_provider(name, _config):
        requested.append(name)
        return Provider(name)

    monkeypatch.setattr("src.embedding.manager.create_provider", create_provider)
    config = SimpleNamespace(embedding_provider_chain=["lmstudio", "ollama"])
    selected = EmbeddingManager(config).select_for_new_index("auto")

    assert selected.name == "ollama"
    assert requested == ["lmstudio", "ollama"]
