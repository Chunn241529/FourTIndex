import ollama

from src.embedding.base import (
    EmbeddingProvider,
    ProviderError,
    ProviderUnavailableError,
)


class OllamaProvider(EmbeddingProvider):
    name = "ollama"

    def __init__(self, model: str, dimension: int, host: str, config=None):
        super().__init__(model, dimension)
        self.client = ollama.Client(host=host)
        
        # Determine max_batch_items dynamically based on VRAM
        from src.config import Config
        cfg = config or Config()
        vram = getattr(cfg, "_detect_vram_mb", lambda: 0)()
        if vram >= 12000:
            self.max_batch_items = 256
        elif vram >= 8000:
            self.max_batch_items = 128
        elif vram > 0:
            self.max_batch_items = 64
        else:
            self.max_batch_items = 32

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
    # LM Studio may return HTTP 500 when multiple embedding batches run concurrently.
    max_parallel_workers = 1

    def __init__(self, model: str, dimension: int, config=None):
        super().__init__(model, dimension)
        from src.config import Config
        self.config = config or Config()
        from src.lmstudio_client import LMStudioClient
        self.lm_client = LMStudioClient(self.config)
        
        # Determine max_batch_items dynamically based on VRAM
        vram = getattr(self.config, "_detect_vram_mb", lambda: 0)()
        if vram >= 12000:
            self.max_batch_items = 128
        elif vram >= 8000:
            self.max_batch_items = 64
        elif vram > 0:
            self.max_batch_items = 32
        else:
            self.max_batch_items = 16

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.request_count += 1
        try:
            res = self.lm_client.embeddings(self.model, texts)
            if "error" in res:
                raise RuntimeError(res["error"])
            data = res.get("data", [])
            sorted_data = sorted(data, key=lambda x: x.get("index", 0))
            embeddings = [x.get("embedding", []) for x in sorted_data]
            return self._validate(embeddings, len(texts))
        except Exception as exc:
            # Fallback to sequential generation on failure (e.g. LMStudio batch issues)
            if len(texts) <= 1:
                if isinstance(exc, ProviderError):
                    raise
                raise ProviderUnavailableError(
                    f"lmstudio model '{self.model}' is unavailable"
                ) from exc
                
            self.request_count -= 1
            fallback_embeddings = []
            for text in texts:
                try:
                    fallback_embeddings.append(self.embed_query(text))
                except Exception as inner_exc:
                    raise ProviderUnavailableError(
                        f"lmstudio model '{self.model}' is unavailable during fallback"
                    ) from inner_exc
            return fallback_embeddings

    def embed_query(self, text: str) -> list[float]:
        self.request_count += 1
        try:
            res = self.lm_client.embeddings(self.model, text)
            if "error" in res:
                raise RuntimeError(res["error"])
            data = res.get("data", [])
            if not data:
                raise RuntimeError("Empty embedding data")
            return data[0].get("embedding", [])
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise
            raise ProviderUnavailableError(
                f"lmstudio model '{self.model}' is unavailable"
            ) from exc


class LocalProvider(EmbeddingProvider):
    name = "local"

    def __init__(self, model: str, dimension: int, config=None):
        super().__init__(model, dimension)
        from src.config import Config
        self.config = config or Config()
        self._st_model = None
        
        # Determine max_batch_items dynamically based on VRAM
        vram = getattr(self.config, "_detect_vram_mb", lambda: 0)()
        if vram >= 12000:
            self.max_batch_items = 256
        elif vram >= 8000:
            self.max_batch_items = 128
        elif vram > 0:
            self.max_batch_items = 64
        else:
            self.max_batch_items = 32

    def _lazy_init(self):
        if self._st_model is None:
            try:
                import os
                from sentence_transformers import SentenceTransformer
                model_path = self.model
                if model_path == "monas-embeddings-text-code":
                    if not os.path.isdir(model_path):
                        model_path = "trungvn2401s/monas-embeddings-text-code"
                self._st_model = SentenceTransformer(model_path)
            except ImportError as exc:
                raise ProviderUnavailableError(
                    "Please install 'sentence-transformers' to use local embedding models."
                ) from exc
            except Exception as exc:
                raise ProviderUnavailableError(
                    f"Failed to load local model '{self.model}'"
                ) from exc

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.request_count += 1
        self._lazy_init()
        try:
            embeddings = self._st_model.encode(texts)
            if hasattr(embeddings, "tolist"):
                embeddings = embeddings.tolist()
            return self._validate(embeddings, len(texts))
        except Exception as exc:
            raise ProviderUnavailableError(
                f"Local model '{self.model}' failed to embed documents"
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
        return OllamaProvider(config.ollama_embedding_model, 0, config.ollama_host, config)
    elif normalized == "local":
        return LocalProvider(config.local_embedding_model, 0, config)
    elif normalized == "fake":
        from tests.test_indexing_service import FakeProvider
        return FakeProvider()
    else:
        raise ProviderError(
            f"Unsupported embedding provider '{name}'; FourTIndex supports 'ollama', 'lmstudio', 'local', and 'fake'"
        )
