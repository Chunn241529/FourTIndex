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
        from src.token_meter import count_tokens
        import sys

        # Setup prompt base to measure non-context token size
        prompt_template_base = (
            f"You are a helpful coding assistant. Answer the user's question based on the provided code context.\n"
            f"Always cite the file names and line numbers of the code you refer to.\n"
            f"If the context doesn't contain enough information, explain what is missing.\n\n"
            f"--- CODE CONTEXT ---\n"
            f"\n\n"
            f"--- USER QUERY ---\n"
            f"{query}\n"
        )
        base_tokens = count_tokens(prompt_template_base, self.model)
        budget = self.config.data.get("budget", {}).get("context_budget_tokens", 35000)

        chunks = context.split("\n\n")
        accepted_chunks = []
        current_tokens = base_tokens
        pruned_count = 0

        for chunk in chunks:
            if not chunk.strip():
                continue
            chunk_tokens = count_tokens(chunk + "\n\n", self.model)
            if current_tokens + chunk_tokens > budget:
                pruned_count += 1
                continue
            accepted_chunks.append(chunk)
            current_tokens += chunk_tokens

        if pruned_count > 0:
            sys.stderr.write(
                f"\n[Warning] Context Guard: Pruned {pruned_count} code chunk(s) to fit within context budget of {budget} tokens "
                f"(Active prompt size: {current_tokens} tokens).\n"
            )

        final_context = "\n\n".join(accepted_chunks)
        prompt = (
            f"You are a helpful coding assistant. Answer the user's question based on the provided code context.\n"
            f"Always cite the file names and line numbers of the code you refer to.\n"
            f"If the context doesn't contain enough information, explain what is missing.\n\n"
            f"--- CODE CONTEXT ---\n"
            f"{final_context}\n\n"
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

    def summarize_code(self, code_content: str, file_path: str = "") -> str:
        """Uses the local LLM to generate a concise summary of the provided code file."""
        from src.token_meter import count_tokens
        
        # Guard against massive files
        budget = 16000
        tokens = count_tokens(code_content, self.model)
        if tokens > budget:
            code_content = code_content[:budget * 4] + "\n...[TRUNCATED DUE TO CONTEXT LIMIT]"
            
        prompt = (
            f"Analyze the following code file '{file_path}' and provide a concise summary (max 3-5 sentences).\n"
            f"Focus on the primary purpose, main classes/functions, and data flow. Do not output markdown code blocks of the original code.\n\n"
            f"--- CODE ---\n{code_content}"
        )
        try:
            if self.provider == "lmstudio":
                messages = [{"role": "user", "content": prompt}]
                response = self.lm_client.chat_completions(self.model, messages)
                if "error" in response:
                    raise RuntimeError(str(response["error"]))
                choices = response.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "No summary generated.").strip()
                return "No summary generated."
            else:
                response = self.client.chat(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.get("message", {}).get("content", "No summary generated.").strip()
        except Exception as e:
            return f"[Summarizer Error] Failed to generate summary: {e}"
