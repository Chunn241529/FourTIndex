import ollama
from src.config import Config

class Embedder:
    def __init__(self, config: Config):
        self.config = config
        self.client = ollama.Client(host=self.config.ollama_host)
        self.model = self.config.ollama_embedding_model

    def get_embedding(self, text: str) -> list[float]:
        """Generates embedding for a single text string using local Ollama service."""
        try:
            response = self.client.embeddings(model=self.model, prompt=text)
            return response.get("embedding", [])
        except Exception as e:
            raise RuntimeError(
                f"Failed to generate embedding via Ollama (Model: {self.model}). "
                f"Please ensure Ollama is running at {self.config.ollama_host}. Error: {e}"
            )

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Generates embeddings for a list of texts in batches to speed up indexing."""
        if not texts:
            return []
            
        batch_size = 16
        all_embeddings = []
        
        try:
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i + batch_size]
                response = self.client.embed(model=self.model, input=batch_texts)
                batch_embs = response.get("embeddings", [])
                all_embeddings.extend(batch_embs)
            return all_embeddings
        except Exception as e:
            # Fallback to sequential generation on failure
            return [self.get_embedding(text) for text in texts]
