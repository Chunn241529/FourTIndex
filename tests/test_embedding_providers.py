import pytest

from src.embedding.base import ProviderError
from src.embedding.providers import OllamaProvider, create_provider


def test_ollama_provider_validates_embeddings(monkeypatch):
    provider = OllamaProvider("test-model", 3, "http://localhost:11434")
    monkeypatch.setattr(
        provider.client,
        "embed",
        lambda **kwargs: {"embeddings": [[1.0, 2.0, 3.0]]},
    )

    assert provider.embed_documents(["document"]) == [[1.0, 2.0, 3.0]]
    assert provider.request_count == 1


def test_create_provider_rejects_third_party_provider():
    config = type(
        "ConfigStub",
        (),
        {
            "ollama_embedding_model": "test-model",
            "ollama_host": "http://localhost:11434",
        },
    )()

    with pytest.raises(ProviderError, match="local Ollama only"):
        create_provider("remote", config)
