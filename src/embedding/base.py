import hashlib
import json
import math
import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass

import httpx


class ProviderError(RuntimeError):
    """Base error raised by an embedding provider."""


class ProviderAuthError(ProviderError):
    pass


class ProviderQuotaError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderInputError(ProviderError):
    pass


class ProviderUnavailableError(ProviderError):
    pass


@dataclass(frozen=True)
class EmbeddingProfile:
    provider: str
    model: str
    dimension: int
    document_mode: str
    query_mode: str
    normalized: bool = True

    @property
    def profile_id(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "EmbeddingProfile":
        return cls(**value)


class EmbeddingProvider(ABC):
    name = "base"
    required_environment: tuple[str, ...] = ()
    max_batch_items = 64

    def __init__(self, model: str, dimension: int):
        self.model = model
        self.dimension = dimension
        self.request_count = 0
        self.token_count = 0

    @property
    def configured(self) -> bool:
        return all(os.environ.get(key) for key in self.required_environment)

    @property
    def missing_environment(self) -> list[str]:
        return [key for key in self.required_environment if not os.environ.get(key)]

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError

    def health_check(self) -> None:
        self.embed_query("fourTIndex embedding provider health check")

    def profile(self) -> EmbeddingProfile:
        return EmbeddingProfile(
            provider=self.name,
            model=self.model,
            dimension=self.dimension,
            document_mode="document",
            query_mode="query",
        )

    def _validate(self, embeddings: list[list[float]], expected_count: int) -> list[list[float]]:
        if len(embeddings) != expected_count:
            raise ProviderInputError(
                f"{self.name} returned {len(embeddings)} vectors for {expected_count} inputs"
            )
        for vector in embeddings:
            if not vector:
                raise ProviderInputError(f"{self.name} returned an empty embedding")
            if self.dimension and len(vector) != self.dimension:
                raise ProviderInputError(
                    f"{self.name} returned dimension {len(vector)}; expected {self.dimension}"
                )
            if any(not math.isfinite(float(value)) for value in vector):
                raise ProviderInputError(f"{self.name} returned a non-finite embedding")
        if not self.dimension and embeddings:
            self.dimension = len(embeddings[0])
        return embeddings


class HTTPEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model: str, dimension: int, timeout_seconds: int):
        super().__init__(model, dimension)
        self.client = httpx.Client(timeout=timeout_seconds)

    def _post(self, url: str, *, headers: dict, payload: dict) -> dict:
        self.request_count += 1
        try:
            response = self.client.post(url, headers=headers, json=payload)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderUnavailableError(f"{self.name} is unavailable") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthError(f"{self.name} rejected its credentials")
        if response.status_code == 429:
            raise ProviderRateLimitError(f"{self.name} rate limit or quota was reached")
        if response.status_code in (400, 404, 413, 422):
            raise ProviderInputError(
                f"{self.name} rejected the embedding request (HTTP {response.status_code})"
            )
        if response.status_code >= 500:
            raise ProviderUnavailableError(
                f"{self.name} failed temporarily (HTTP {response.status_code})"
            )
        if not response.is_success:
            raise ProviderError(f"{self.name} failed (HTTP {response.status_code})")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(f"{self.name} returned invalid JSON") from exc

    @staticmethod
    def _openai_vectors(data: dict) -> list[list[float]]:
        items = data.get("data", [])
        return [item["embedding"] for item in sorted(items, key=lambda item: item.get("index", 0))]
