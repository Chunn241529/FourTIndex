import os
import sys
import yaml

class Config:
    def __init__(self, config_path=None):
        if config_path is None:
            # Find config.yaml in the project root (parent of 'src')
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(project_root, "config.yaml")
        self.config_path = os.path.abspath(config_path)
        self.data = {}
        self.load()

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
        return self.data.get("project", {}).get("name", "fourTindex")

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
        return self.data.get("ollama", {}).get("host", "http://localhost:11434")

    @property
    def ollama_embedding_model(self) -> str:
        return self.data.get("ollama", {}).get("embedding_model", "nomic-embed-text")

    @property
    def ollama_llm_model(self) -> str:
        return self.data.get("ollama", {}).get("llm_model", "qwen2.5-coder:7b")
