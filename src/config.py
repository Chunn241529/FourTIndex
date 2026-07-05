import os
import sys
import yaml
from dotenv import load_dotenv


PROVIDER_DEFAULTS = {
    "voyage": {"model": "voyage-code-3", "dimension": 1024},
    "jina": {"model": "jina-embeddings-v4", "dimension": 1024},
    "cloudflare": {"model": "@cf/qwen/qwen3-embedding-0.6b", "dimension": 1024},
    "pinecone": {"model": "llama-text-embed-v2", "dimension": 1024},
    "gemini": {"model": "gemini-embedding-2", "dimension": 768},
    "cohere": {"model": "embed-v4.0", "dimension": 1024},
    "nvidia": {"model": "nvidia/nv-embedcode-7b-v1", "dimension": 4096},
    "ollama": {"model": "qwen3-embedding:4b", "dimension": 0},
}

class Config:
    def __init__(self, config_path=None):
        if config_path is None:
            # Find config.yaml in the project root (parent of 'src')
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(project_root, "config.yaml")
        self.config_path = os.path.abspath(config_path)
        env_path = os.environ.get("FOURTINDEX_ENV_FILE") or os.path.join(
            os.path.dirname(self.config_path), ".env"
        )
        load_dotenv(env_path, override=False)
        self.data = {}
        self.load()

    def _int_value(self, section: str, key: str, default: int) -> int:
        value = self.data.get(section, {}).get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def load(self):
        """Loads configuration from yaml file."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.data = yaml.safe_load(f) or {}
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to load config from {self.config_path}: {e}\n")
                self.data = {}
        else:
            # If not found, try to locate in the project root of this code file
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            fallback_path = os.path.join(project_root, "config.yaml")
            if os.path.exists(fallback_path):
                self.config_path = fallback_path
                try:
                    with open(fallback_path, "r", encoding="utf-8") as f:
                        self.data = yaml.safe_load(f) or {}
                except Exception as e:
                    sys.stderr.write(f"Warning: Failed to load config from fallback {fallback_path}: {e}\n")
                    self.data = {}
            else:
                self.data = {}

    @property
    def project_name(self) -> str:
        return self.data.get("project", {}).get("name", "FourTIndex")

    @property
    def exclude_dirs(self) -> list:
        return self.data.get("project", {}).get("exclude_dirs", [
            ".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv", ".fourtindex", "fourtindex.egg-info"
        ])

    @property
    def supported_extensions(self) -> list:
        return self.data.get("project", {}).get("supported_extensions", [
            ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".md", ".txt"
        ])

    @property
    def db_persist_directory(self) -> str:
        path = self.data.get("database", {}).get("persist_directory", "./.fourtindex/db")
        if not os.path.isabs(path):
            config_dir = os.path.dirname(self.config_path)
            return os.path.abspath(os.path.join(config_dir, path)).replace("\\", "/")
        return os.path.abspath(path).replace("\\", "/")

    @property
    def ollama_host(self) -> str:
        return os.environ.get("OLLAMA_HOST") or self.data.get("ollama", {}).get(
            "host", "http://localhost:11434"
        )

    @property
    def ollama_embedding_model(self) -> str:
        return self.data.get("ollama", {}).get("embedding_model", "nomic-embed-text")

    @property
    def ollama_llm_model(self) -> str:
        return self.data.get("ollama", {}).get("llm_model", "qwen2.5-coder:7b")

    @property
    def embedding_provider_chain(self) -> list[str]:
        env_value = os.environ.get("FOURTINDEX_EMBEDDING_PROVIDER_CHAIN")
        if env_value:
            providers = [item.strip().lower() for item in env_value.split(",") if item.strip()]
        else:
            providers = self.data.get("embedding", {}).get("provider_chain", ["ollama"])
        return list(dict.fromkeys(providers or ["ollama"]))

    @property
    def embedding_batch_size(self) -> int:
        return max(1, self._int_value("embedding", "batch_size", 64))

    @property
    def embedding_batch_max_chars(self) -> int:
        return max(1, self._int_value("embedding", "batch_max_chars", 250000))

    @property
    def embedding_retry_attempts(self) -> int:
        return max(0, self._int_value("embedding", "retry_attempts", 2))

    @property
    def embedding_timeout_seconds(self) -> int:
        return max(1, self._int_value("embedding", "request_timeout_seconds", 60))

    @property
    def parse_workers(self) -> int:
        configured = self._int_value("indexing", "parse_workers", 0)
        return configured if configured > 0 else min(8, max(1, os.cpu_count() or 1))

    @property
    def commit_batch_files(self) -> int:
        return max(1, self._int_value("indexing", "commit_batch_files", 32))

    @property
    def max_file_size_bytes(self) -> int:
        return max(1, self._int_value("indexing", "max_file_size_bytes", 2097152))

    @property
    def respect_gitignore(self) -> bool:
        return bool(self.data.get("indexing", {}).get("respect_gitignore", True))

    @property
    def exclude_globs(self) -> list[str]:
        return list(self.data.get("indexing", {}).get("exclude_globs", []))

    def embedding_provider_settings(self, provider_name: str) -> dict:
        name = provider_name.lower()
        defaults = dict(PROVIDER_DEFAULTS.get(name, {}))
        configured = self.data.get("embedding", {}).get("providers", {}).get(name, {})
        defaults.update(configured)
        if name == "ollama":
            defaults["model"] = self.ollama_embedding_model
        return defaults
