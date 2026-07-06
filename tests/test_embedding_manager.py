from types import SimpleNamespace

from src.config import Config
from src.embedding.manager import EmbeddingManager


class StubProvider:
    name = "ollama"

    def health_check(self):
        return None


def test_auto_selection_resolves_to_ollama(monkeypatch):
    requested = []

    def create_provider(name, _config):
        requested.append(name)
        return StubProvider()

    monkeypatch.setattr("src.embedding.manager.create_provider", create_provider)

    selected = EmbeddingManager(SimpleNamespace()).select_for_new_index("auto")

    assert selected.name == "ollama"
    assert requested == ["auto"]


def test_provider_chain_is_always_local(monkeypatch):
    monkeypatch.setenv("FOURTINDEX_EMBEDDING_PROVIDER_CHAIN", "remote,ollama")

    config = Config("missing-config.yaml")

    assert config.embedding_provider_chain == ["ollama"]
