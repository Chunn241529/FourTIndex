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


class LMStudioProvider(EmbeddingProvider):
    name = "lmstudio"
    max_batch_items = 16

    def __init__(self, model: str, dimension: int, config):
        super().__init__(model, dimension)
        self.config = config
        from src.lmstudio_client import LMStudioClient
        self.lm_client = LMStudioClient(config)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.request_count += 1
        try:
            res = self.lm_client.embeddings(self.model, texts)
            if "error" in res:
                raise ProviderUnavailableError(
                    f"lmstudio model '{self.model}' is unavailable: {res['error']}"
                )
            data = res.get("data", [])
            sorted_data = sorted(data, key=lambda x: x.get("index", 0))
            embeddings = [x.get("embedding", []) for x in sorted_data]
            return self._validate(embeddings, len(texts))
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise
            raise ProviderUnavailableError(
                f"lmstudio model '{self.model}' is unavailable"
            ) from exc

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def create_provider(name: str, config) -> EmbeddingProvider:
    normalized = name.lower()
    if normalized == "auto":
        normalized = config.llm_provider.lower()

    if normalized == "lmstudio":
        return LMStudioProvider(config.lmstudio_embedding_model, 0, config)
    elif normalized == "ollama":
        return OllamaProvider(config.ollama_embedding_model, 0, config.ollama_host)
    else:
        raise ProviderError(
            f"Unsupported embedding provider '{name}'; FourTIndex supports 'ollama' and 'lmstudio'"
        )

