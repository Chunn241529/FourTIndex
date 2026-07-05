import time

from src.config import PROVIDER_DEFAULTS, Config
from src.embedding.base import (
    EmbeddingProfile,
    EmbeddingProvider,
    ProviderError,
    ProviderInputError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from src.embedding.providers import create_provider


class EmbeddingManager:
    def __init__(self, config: Config):
        self.config = config
        self.provider: EmbeddingProvider | None = None

    def select_for_new_index(self, requested: str = "auto") -> EmbeddingProvider:
        names = [requested.lower()] if requested != "auto" else self.config.embedding_provider_chain
        errors = []
        for name in names:
            try:
                provider = create_provider(name, self.config)
                if not provider.configured:
                    errors.append(f"{name}: missing {', '.join(provider.missing_environment)}")
                    continue
                provider.health_check()
                self.provider = provider
                return provider
            except ProviderError as exc:
                errors.append(f"{name}: {exc}")
        detail = "; ".join(errors) if errors else "no providers were enabled"
        raise ProviderUnavailableError(f"No embedding provider is available ({detail})")

    def load_profile(self, profile: EmbeddingProfile) -> EmbeddingProvider:
        provider = create_provider(profile.provider, self.config)
        if not provider.configured:
            missing = ", ".join(provider.missing_environment)
            raise ProviderUnavailableError(
                f"Pinned provider '{profile.provider}' is not configured; missing {missing}. "
                "Reconfigure it or rebuild with --embedding-provider ollama."
            )
        provider.model = profile.model
        provider.dimension = profile.dimension
        self.provider = provider
        return provider

    def provider_statuses(self, check: bool = False) -> list[dict]:
        names = list(PROVIDER_DEFAULTS)
        statuses = []
        for name in names:
            provider = create_provider(name, self.config)
            state = "configured" if provider.configured else "missing credentials"
            if check and provider.configured:
                try:
                    provider.health_check()
                    state = "ready"
                except ProviderError as exc:
                    state = str(exc)
            statuses.append(
                {
                    "provider": name,
                    "model": provider.model,
                    "dimension": provider.dimension or "auto",
                    "state": state,
                    "enabled": name in self.config.embedding_provider_chain,
                }
            )
        return statuses

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
            return self.embed_documents(texts[:midpoint]) + self.embed_documents(texts[midpoint:])

    def embed_query(self, text: str) -> list[float]:
        if not self.provider:
            raise ProviderError("No embedding provider has been selected")
        return self._retry(lambda: self.provider.embed_query(text))

    def _retry(self, operation):
        attempts = self.config.embedding_retry_attempts + 1
        for attempt in range(attempts):
            try:
                return operation()
            except (ProviderRateLimitError, ProviderUnavailableError):
                if attempt + 1 >= attempts:
                    raise
                time.sleep(0.25 * (2**attempt))
        raise ProviderError("Embedding retry loop exited unexpectedly")
