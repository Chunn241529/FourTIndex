import ollama
from src.config import Config
from src.lmstudio_client import LMStudioClient

class LLMClient:
    def __init__(self, config: Config):
        self.config = config
        self.provider = self.config.llm_provider
        
        if self.provider == "lmstudio":
            self.lm_client = LMStudioClient(self.config)
            self.model = self.config.lmstudio_llm_model
        else:
            self.client = ollama.Client(host=self.config.ollama_host)
            self.model = self.config.ollama_llm_model

    def generate_answer(self, query: str, context: str) -> str:
        """Queries the configured LLM model (Ollama or LM Studio) with the retrieved code context."""
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
            if self.provider == "lmstudio":
                messages = [{"role": "user", "content": prompt}]
                response = self.lm_client.chat_completions(self.model, messages)
                if "error" in response:
                    raise RuntimeError(str(response["error"]))
                choices = response.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "No response generated.")
                return "No response generated."
            else:
                response = self.client.chat(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.get("message", {}).get("content", "No response generated.")
        except Exception as e:
            if self.provider == "lmstudio":
                return (
                    f"Error communicating with local LM Studio model '{self.model}': {e}\n"
                    f"Please verify that LM Studio server is running at {self.config.lmstudio_host} and has model '{self.model}' loaded."
                )
            else:
                return (
                    f"Error communicating with local Ollama model '{self.model}': {e}\n"
                    f"Please verify that Ollama is running and you have pulled the model using 'ollama pull {self.model}'."
                )

