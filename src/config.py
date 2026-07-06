import os
import sys
import yaml
from dotenv import load_dotenv


class Config:
    def __init__(self, config_path=None):
        if config_path is None:
            config_path = os.environ.get("FOURTINDEX_CONFIG_PATH")

        if config_path is None:
            # Check global user config directory (~/.fourtindex/config.yaml)
            global_dir = os.path.expanduser("~/.fourtindex")
            global_config = os.path.join(global_dir, "config.yaml")

            # Determine where the default template configuration is
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            default_config = os.path.join(project_root, "config.yaml")
            if not os.path.exists(default_config):
                package_dir = os.path.dirname(os.path.abspath(__file__))
                default_config = os.path.join(package_dir, "config.yaml")

            # If default template config is found, initialize global config from it
            if os.path.exists(default_config):
                if not os.path.exists(global_config):
                    try:
                        os.makedirs(global_dir, exist_ok=True)
                        import shutil
                        shutil.copy2(default_config, global_config)
                        sys.stderr.write(f"Initialized global configuration at: {global_config}\n")
                    except Exception as e:
                        sys.stderr.write(f"Warning: Failed to copy default config to {global_config}: {e}\n")
                config_path = global_config
            else:
                # If template config is not found, fallback to global_config if it exists
                if os.path.exists(global_config):
                    config_path = global_config

        if config_path is None:
            # Fallback to local project root default
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
            if not os.path.exists(fallback_path):
                package_dir = os.path.dirname(os.path.abspath(__file__))
                fallback_path = os.path.join(package_dir, "config.yaml")

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
            ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".md", ".txt",
            ".rs", ".go", ".java", ".kt", ".swift", ".cs", ".cpp", ".h", ".gd", ".lua"
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
        return ["ollama"]

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

    @property
    def context_budget_tokens(self) -> int:
        return self._int_value("budget", "context_budget_tokens", 35000)

    @property
    def context_budget_usd(self) -> float:
        val = self.data.get("budget", {}).get("context_budget_usd", 0.50)
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.50

