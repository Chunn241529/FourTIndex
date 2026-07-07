import ollama
from src.config import Config
from src.lmstudio_client import LMStudioClient

class Embedder:
    def __init__(self, config: Config):
        self.config = config
        self.provider = self.config.llm_provider
        
        if self.provider == "lmstudio":
            self.lm_client = LMStudioClient(self.config)
            self.model = self.config.lmstudio_embedding_model
        else:
            self.client = ollama.Client(host=self.config.ollama_host)
            self.model = self.config.ollama_embedding_model

    def get_embedding(self, text: str) -> list[float]:
        """Generates embedding for a single text string using the configured provider (Ollama or LM Studio)."""
        try:
            if self.provider == "lmstudio":
                response = self.lm_client.embeddings(self.model, text)
                if "error" in response:
                    raise RuntimeError(str(response["error"]))
                data = response.get("data", [])
                if data:
                    return data[0].get("embedding", [])
                return []
            else:
                response = self.client.embeddings(model=self.model, prompt=text)
                return response.get("embedding", [])
        except Exception as e:
            raise RuntimeError(
                f"Failed to generate embedding via {self.provider.upper()} (Model: {self.model}). "
                f"Please ensure the service is running. Error: {e}"
            )

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Generates embeddings for a list of texts in batches to speed up indexing."""
        if not texts:
            return []
            
        batch_size = 16
        all_embeddings = []
        
        try:
            if self.provider == "lmstudio":
                for i in range(0, len(texts), batch_size):
                    batch_texts = texts[i:i + batch_size]
                    response = self.lm_client.embeddings(self.model, batch_texts)
                    if "error" in response:
                        raise RuntimeError(str(response["error"]))
                    data = response.get("data", [])
                    # Sort by index to preserve input ordering
                    sorted_data = sorted(data, key=lambda x: x.get("index", 0))
                    batch_embs = [x.get("embedding", []) for x in sorted_data]
                    all_embeddings.extend(batch_embs)
                return all_embeddings
            else:
                for i in range(0, len(texts), batch_size):
                    batch_texts = texts[i:i + batch_size]
                    response = self.client.embed(model=self.model, input=batch_texts)
                    batch_embs = response.get("embeddings", [])
                    all_embeddings.extend(batch_embs)
                return all_embeddings
        except Exception as e:
            # Fallback to sequential generation on failure
            return [self.get_embedding(text) for text in texts]

