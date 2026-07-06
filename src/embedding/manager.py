import time

from src.config import Config
from src.embedding.base import (
    EmbeddingProfile,
    EmbeddingProvider,
    ProviderError,
    ProviderInputError,
    ProviderUnavailableError,
)
from src.embedding.providers import create_provider


class EmbeddingManager:
    def __init__(self, config: Config):
        self.config = config
        self.provider: EmbeddingProvider | None = None

    def select_for_new_index(self, requested: str = "auto") -> EmbeddingProvider:
        provider = create_provider(requested, self.config)
        provider.health_check()
        self.provider = provider
        return provider

    def load_profile(self, profile: EmbeddingProfile) -> EmbeddingProvider:
        provider = create_provider(profile.provider, self.config)
        provider.model = profile.model
        provider.dimension = profile.dimension
        self.provider = provider
        return provider

    def provider_statuses(self, check: bool = False) -> list[dict]:
        provider = create_provider("ollama", self.config)
        state = "configured"
        if check:
            try:
                provider.health_check()
                state = "ready"
            except ProviderError as exc:
                state = str(exc)
        return [
            {
                "provider": provider.name,
                "model": provider.model,
                "dimension": provider.dimension or "auto",
                "state": state,
                "enabled": True,
            }
        ]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not self.provider:
            raise ProviderError("No embedding provider has been selected")
        if not texts:
            return []
        try:
            return self._retry(lambda: self.provider.embed_documents(texts))
        except ProviderInputError:
            if len(texts) == 1:
                raise
            midpoint = len(texts) // 2
            return self.embed_documents(texts[:midpoint]) + self.embed_documents(
                texts[midpoint:]
            )

    def embed_query(self, text: str) -> list[float]:
        if not self.provider:
            raise ProviderError("No embedding provider has been selected")
        return self._retry(lambda: self.provider.embed_query(text))

    def _retry(self, operation):
        attempts = self.config.embedding_retry_attempts + 1
        for attempt in range(attempts):
            try:
                return operation()
            except ProviderUnavailableError:
                if attempt + 1 >= attempts:
                    raise
                time.sleep(0.25 * (2**attempt))
        raise ProviderError("Embedding retry loop exited unexpectedly")
