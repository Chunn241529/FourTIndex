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
            "llm_provider": "ollama",
        },
    )()

    with pytest.raises(ProviderError, match="supports 'ollama', 'lmstudio', and 'fake'"):
        create_provider("remote", config)


def test_lmstudio_provider_validates_embeddings(monkeypatch):
    config = type(
        "ConfigStub",
        (),
        {
            "lmstudio_embedding_model": "test-model",
            "lmstudio_host": "http://localhost:2401",
            "lmstudio_api_token": "token",
            "llm_provider": "lmstudio",
        },
    )()
    provider = create_provider("lmstudio", config)

    monkeypatch.setattr(
        provider.lm_client,
        "embeddings",
        lambda model, text_or_texts: {"data": [{"embedding": [1.0, 2.0, 3.0], "index": 0}]},
    )

    assert provider.embed_documents(["document"]) == [[1.0, 2.0, 3.0]]
    assert provider.request_count == 1
