import pytest

from src.embedding.providers import (
    CloudflareProvider,
    CohereProvider,
    GeminiProvider,
    JinaProvider,
    NvidiaProvider,
    PineconeProvider,
    VoyageProvider,
)


@pytest.mark.parametrize(
    ("provider_type", "environment", "response"),
    [
        (VoyageProvider, {"VOYAGE_API_KEY": "secret"}, {"data": [{"index": 0, "embedding": [1, 2, 3]}]}),
        (JinaProvider, {"JINA_API_KEY": "secret"}, {"data": [{"index": 0, "embedding": [1, 2, 3]}]}),
        (
            CloudflareProvider,
            {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "secret"},
            {"result": {"data": [[1, 2, 3]]}},
        ),
        (PineconeProvider, {"PINECONE_API_KEY": "secret"}, {"data": [{"values": [1, 2, 3]}]}),
        (GeminiProvider, {"GEMINI_API_KEY": "secret"}, {"embeddings": [{"values": [1, 2, 3]}]}),
        (CohereProvider, {"COHERE_API_KEY": "secret"}, {"embeddings": {"float": [[1, 2, 3]]}}),
        (NvidiaProvider, {"NVIDIA_API_KEY": "secret"}, {"data": [{"index": 0, "embedding": [1, 2, 3]}]}),
    ],
)
def test_cloud_provider_response_validation(
    monkeypatch, provider_type, environment, response
):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    provider = provider_type("test-model", 3, 1)
    monkeypatch.setattr(provider, "_post", lambda *args, **kwargs: response)

    assert provider.configured
    assert provider.embed_documents(["document"]) == [[1, 2, 3]]
    assert provider.embed_query("query") == [1, 2, 3]


def test_provider_requires_all_credentials(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "secret")
    provider = CloudflareProvider("model", 3, 1)

    assert not provider.configured
    assert provider.missing_environment == ["CLOUDFLARE_ACCOUNT_ID"]
