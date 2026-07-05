import ollama
from src.config import Config

class LLMClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = ollama.Client(host=self.config.ollama_host)
        self.model = self.config.ollama_llm_model

    def generate_answer(self, query: str, context: str) -> str:
        """Queries the local Ollama LLM model with the retrieved code context."""
        prompt = (
            f"You are a helpful coding assistant. Answer the user's question based on the provided code context.\n"
            f"Always cite the file names and line numbers of the code you refer to.\n"
            f"If the context doesn't contain enough information, explain what is missing.\n\n"
            f"--- CODE CONTEXT ---\n"
            f"{context}\n\n"
            f"--- USER QUERY ---\n"
            f"{query}\n"
        )
        try:
            response = self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.get("message", {}).get("content", "No response generated.")
        except Exception as e:
            return (
                f"Error communicating with local LLM model '{self.model}': {e}\n"
                f"Please verify that Ollama is running and you have pulled the model using 'ollama pull {self.model}'."
            )
