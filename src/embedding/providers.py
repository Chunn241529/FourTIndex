import ollama

from src.embedding.base import (
    EmbeddingProvider,
    ProviderError,
    ProviderUnavailableError,
)


class OllamaProvider(EmbeddingProvider):
    name = "ollama"
    max_batch_items = 64

    def __init__(self, model: str, dimension: int, host: str):
        super().__init__(model, dimension)
        self.client = ollama.Client(host=host)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.request_count += 1
        try:
            response = self.client.embed(model=self.model, input=texts)
        except Exception as exc:
            raise ProviderUnavailableError(
                f"ollama model '{self.model}' is unavailable"
            ) from exc
        return self._validate(list(response.get("embeddings", [])), len(texts))

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def create_provider(name: str, config) -> EmbeddingProvider:
    normalized = name.lower()
    if normalized not in ("auto", "ollama"):
        raise ProviderError(
            f"Unsupported embedding provider '{name}'; FourTIndex uses local Ollama only"
        )
    return OllamaProvider(config.ollama_embedding_model, 0, config.ollama_host)
