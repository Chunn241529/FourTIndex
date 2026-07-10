import json
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional
from src.config import Config

class LMStudioClient:
    def __init__(self, config: Config):
        self.config = config
        self.host = self.config.lmstudio_host
        self.api_token = self.config.lmstudio_api_token

    def _request(self, path: str, method: str = "GET", data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Performs HTTP request to LM Studio API server."""
        url = f"{self.host.rstrip('/')}{path}"
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        req_data = None
        if data is not None:
            req_data = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_content = e.read().decode("utf-8")
            try:
                err_json = json.loads(err_content)
                return {"error": err_json}
            except Exception:
                return {"error": err_content or str(e)}
        except Exception as e:
            return {"error": str(e)}

    def list_models(self) -> Dict[str, Any]:
        """Lists all downloaded and loaded models via GET /api/v1/models."""
        return self._request("/api/v1/models", method="GET")

    def load_model(self, model: str, context_length: Optional[int] = None, extra_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Loads a model into memory via POST /api/v1/models/load."""
        payload = {"model": model}
        if context_length is not None:
            payload["context_length"] = context_length
        if extra_config:
            payload.update(extra_config)
        return self._request("/api/v1/models/load", method="POST", data=payload)

    def unload_model(self, model: str, instance_id: Optional[str] = None) -> Dict[str, Any]:
        """Unloads a model from memory via POST /api/v1/models/unload."""
        payload = {"model": model}
        if instance_id:
            payload["instance_id"] = instance_id
        return self._request("/api/v1/models/unload", method="POST", data=payload)

    def download_model(self, model_url_or_repo: str) -> Dict[str, Any]:
        """Requests downloading a model via POST /api/v1/models/download."""
        return self._request("/api/v1/models/download", method="POST", data={"model": model_url_or_repo})

    def get_download_status(self) -> Dict[str, Any]:
        """Checks the download progress via GET /api/v1/models/download/status."""
        return self._request("/api/v1/models/download/status", method="GET")

    def chat(self, model: str, message: str, context_length: Optional[int] = None) -> Dict[str, Any]:
        """Performs a stateful native chat completion request via POST /api/v1/chat."""
        payload = {
            "model": model,
            "input": message
        }
        if context_length is not None:
            payload["context_length"] = context_length
        return self._request("/api/v1/chat", method="POST", data=payload)

    def chat_completions(self, model: str, messages: List[Dict[str, str]], stream: bool = False, temperature: float = 0.7, max_tokens: Optional[int] = None) -> Dict[str, Any]:
        """Performs OpenAI-compatible chat completion via POST /v1/chat/completions."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return self._request("/v1/chat/completions", method="POST", data=payload)

    def embeddings(self, model: str, text_or_texts: Any) -> Dict[str, Any]:
        """Performs OpenAI-compatible embedding generation via POST /v1/embeddings."""
        payload = {
            "model": model,
            "input": text_or_texts
        }
        return self._request("/v1/embeddings", method="POST", data=payload)
