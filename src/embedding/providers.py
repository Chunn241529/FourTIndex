import os

import ollama

from src.embedding.base import (
    EmbeddingProfile,
    EmbeddingProvider,
    HTTPEmbeddingProvider,
    ProviderError,
    ProviderUnavailableError,
)


def _usage_tokens(data: dict) -> int:
    usage = data.get("usage") or data.get("meta", {}).get("billed_units") or {}
    return int(
        usage.get("total_tokens")
        or usage.get("input_tokens")
        or usage.get("inputTokens")
        or 0
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
            raise ProviderUnavailableError(f"ollama model '{self.model}' is unavailable") from exc
        return self._validate(list(response.get("embeddings", [])), len(texts))

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class VoyageProvider(HTTPEmbeddingProvider):
    name = "voyage"
    required_environment = ("VOYAGE_API_KEY",)
    max_batch_items = 1000
    endpoint = "https://api.voyageai.com/v1/embeddings"

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        data = self._post(
            self.endpoint,
            headers={"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}"},
            payload={"input": texts, "model": self.model, "input_type": input_type},
        )
        self.token_count += _usage_tokens(data)
        vectors = self._openai_vectors(data) or data.get("embeddings", [])
        return self._validate(vectors, len(texts))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]


class JinaProvider(HTTPEmbeddingProvider):
    name = "jina"
    required_environment = ("JINA_API_KEY",)
    max_batch_items = 128
    endpoint = "https://api.jina.ai/v1/embeddings"

    def _embed(self, texts: list[str]) -> list[list[float]]:
        data = self._post(
            self.endpoint,
            headers={"Authorization": f"Bearer {os.environ['JINA_API_KEY']}"},
            payload={
                "model": self.model,
                "input": texts,
                "task": "code",
                "dimensions": self.dimension,
                "normalized": True,
                "embedding_type": "float",
            },
        )
        self.token_count += _usage_tokens(data)
        return self._validate(self._openai_vectors(data), len(texts))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def profile(self) -> EmbeddingProfile:
        return EmbeddingProfile(self.name, self.model, self.dimension, "code", "code", True)


class CloudflareProvider(HTTPEmbeddingProvider):
    name = "cloudflare"
    required_environment = ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN")
    max_batch_items = 100

    @property
    def endpoint(self) -> str:
        account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
        return f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{self.model}"

    def _embed(self, texts: list[str]) -> list[list[float]]:
        data = self._post(
            self.endpoint,
            headers={"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}"},
            payload={"text": texts},
        )
        result = data.get("result", data)
        vectors = result.get("data", result.get("embeddings", []))
        if vectors and isinstance(vectors[0], dict):
            vectors = [item.get("embedding", item.get("values", [])) for item in vectors]
        return self._validate(vectors, len(texts))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


class PineconeProvider(HTTPEmbeddingProvider):
    name = "pinecone"
    required_environment = ("PINECONE_API_KEY",)
    max_batch_items = 96
    endpoint = "https://api.pinecone.io/embed"

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        data = self._post(
            self.endpoint,
            headers={
                "Api-Key": os.environ["PINECONE_API_KEY"],
                "X-Pinecone-API-Version": "2025-10",
            },
            payload={
                "model": self.model,
                "inputs": [{"text": text} for text in texts],
                "parameters": {
                    "input_type": input_type,
                    "truncate": "END",
                    "dimension": self.dimension,
                },
            },
        )
        self.token_count += _usage_tokens(data)
        vectors = [item.get("values", item.get("embedding", [])) for item in data.get("data", [])]
        return self._validate(vectors, len(texts))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "passage")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]

    def profile(self) -> EmbeddingProfile:
        return EmbeddingProfile(self.name, self.model, self.dimension, "passage", "query", True)


class GeminiProvider(HTTPEmbeddingProvider):
    name = "gemini"
    required_environment = ("GEMINI_API_KEY",)
    max_batch_items = 100

    @property
    def endpoint(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents"

    def _embed(self, texts: list[str], query: bool) -> list[list[float]]:
        prepared = [
            f"task: code retrieval | query: {text}" if query else f"title: none | text: {text}"
            for text in texts
        ]
        requests = [
            {
                "model": f"models/{self.model}",
                "content": {"parts": [{"text": text}]},
                "outputDimensionality": self.dimension,
            }
            for text in prepared
        ]
        data = self._post(
            self.endpoint,
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            payload={"requests": requests},
        )
        vectors = [item.get("values", []) for item in data.get("embeddings", [])]
        return self._validate(vectors, len(texts))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, False)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], True)[0]

    def profile(self) -> EmbeddingProfile:
        return EmbeddingProfile(
            self.name, self.model, self.dimension, "code_document_prefix", "code_query_prefix", True
        )


class CohereProvider(HTTPEmbeddingProvider):
    name = "cohere"
    required_environment = ("COHERE_API_KEY",)
    max_batch_items = 96
    endpoint = "https://api.cohere.com/v2/embed"

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        data = self._post(
            self.endpoint,
            headers={"Authorization": f"Bearer {os.environ['COHERE_API_KEY']}"},
            payload={
                "model": self.model,
                "texts": texts,
                "input_type": input_type,
                "embedding_types": ["float"],
                "output_dimension": self.dimension,
            },
        )
        self.token_count += _usage_tokens(data)
        vectors = data.get("embeddings", {}).get("float", [])
        return self._validate(vectors, len(texts))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "search_document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "search_query")[0]

    def profile(self) -> EmbeddingProfile:
        return EmbeddingProfile(
            self.name, self.model, self.dimension, "search_document", "search_query", True
        )


class NvidiaProvider(HTTPEmbeddingProvider):
    name = "nvidia"
    required_environment = ("NVIDIA_API_KEY",)
    max_batch_items = 32
    endpoint = "https://integrate.api.nvidia.com/v1/embeddings"
    query_instruction = "Instruct: Retrieve code or text based on user query.\nQuery: "

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        prepared = [self.query_instruction + text for text in texts] if input_type == "query" else texts
        data = self._post(
            self.endpoint,
            headers={"Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}"},
            payload={"input": prepared, "model": self.model, "input_type": input_type},
        )
        self.token_count += _usage_tokens(data)
        return self._validate(self._openai_vectors(data), len(texts))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "passage")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]

    def profile(self) -> EmbeddingProfile:
        return EmbeddingProfile(
            self.name, self.model, self.dimension, "passage", "instruct_query", True
        )


PROVIDER_TYPES = {
    provider.name: provider
    for provider in (
        VoyageProvider,
        JinaProvider,
        CloudflareProvider,
        PineconeProvider,
        GeminiProvider,
        CohereProvider,
        NvidiaProvider,
    )
}


def create_provider(name: str, config) -> EmbeddingProvider:
    settings = config.embedding_provider_settings(name)
    if name == "ollama":
        return OllamaProvider(settings["model"], settings.get("dimension", 0), config.ollama_host)
    provider_type = PROVIDER_TYPES.get(name)
    if not provider_type:
        raise ProviderError(f"Unknown embedding provider: {name}")
    return provider_type(
        settings["model"], settings["dimension"], config.embedding_timeout_seconds
    )
