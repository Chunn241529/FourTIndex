import hashlib
import json
import math
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass


class ProviderError(RuntimeError):
    """Base error raised by the local embedding provider."""


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
    max_batch_items = 64

    def __init__(self, model: str, dimension: int):
        self.model = model
        self.dimension = dimension
        self.request_count = 0
        self.token_count = 0

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

    def _validate(
        self, embeddings: list[list[float]], expected_count: int
    ) -> list[list[float]]:
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
                raise ProviderInputError(
                    f"{self.name} returned a non-finite embedding"
                )
        if not self.dimension and embeddings:
            self.dimension = len(embeddings[0])
        return embeddings
