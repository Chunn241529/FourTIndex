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

    def _ensure_only_model_loaded(self, model: str, load_if_missing: bool = True) -> None:
        """Ensures that ONLY the specified model is loaded in memory.
        Unloads any other models that are currently loaded.
        If the target model is not loaded and load_if_missing is True, loads it.
        """
        try:
            loaded = self.list_models()
            models_data = loaded.get("models", []) or loaded.get("data", [])
            
            target_is_loaded = False
            other_models_to_unload = []
            
            for m in models_data:
                model_key = m.get("key") or m.get("id")
                instances = m.get("loaded_instances", [])
                
                is_currently_loaded = False
                inst_ids = []
                if instances:
                    is_currently_loaded = True
                    for inst in instances:
                        inst_id = inst.get("id") or inst.get("instance_identifier")
                        if inst_id:
                            inst_ids.append(inst_id)
                else:
                    inst_id = m.get("instance_identifier") or m.get("instance_id")
                    if inst_id:
                        is_currently_loaded = True
                        inst_ids.append(inst_id)
                
                if is_currently_loaded:
                    if model_key == model:
                        target_is_loaded = True
                    else:
                        other_models_to_unload.append((model_key, inst_ids))
            
            # Unload other models
            for model_key, inst_ids in other_models_to_unload:
                if inst_ids:
                    for inst_id in inst_ids:
                        self.unload_model(model_key, instance_id=inst_id)
                else:
                    self.unload_model(model_key)
            
            # If the target model is not loaded and load_if_missing is True, load it
            if not target_is_loaded and load_if_missing:
                payload = {"model": model}
                self._request("/api/v1/models/load", method="POST", data=payload)
                
        except Exception as e:
            import logging
            logging.getLogger("fourTindex.lmstudio_client").warning(
                f"Failed to ensure only model '{model}' is loaded: {e}"
            )

    def load_model(self, model: str, context_length: Optional[int] = None, extra_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Loads a model into memory via POST /api/v1/models/load."""
        self._ensure_only_model_loaded(model, load_if_missing=False)
        payload = {"model": model}
        if context_length is not None:
            payload["context_length"] = context_length
        if extra_config:
            payload.update(extra_config)
        return self._request("/api/v1/models/load", method="POST", data=payload)

    def unload_model(self, model: str, instance_id: Optional[str] = None) -> Dict[str, Any]:
        """Unloads a model from memory via POST /api/v1/models/unload."""
        if not instance_id:
            try:
                loaded = self.list_models()
                models_data = loaded.get("models", []) or loaded.get("data", [])
                for m in models_data:
                    model_id = m.get("key") or m.get("id")
                    if model_id == model:
                        instances = m.get("loaded_instances", [])
                        if instances:
                            instance_id = instances[0].get("id") or instances[0].get("instance_identifier")
                        else:
                            instance_id = m.get("instance_identifier") or m.get("instance_id") or m.get("id")
                        break
            except Exception:
                pass
        
        if not instance_id:
            instance_id = model

        payload = {"instance_id": instance_id}
        return self._request("/api/v1/models/unload", method="POST", data=payload)

    def unload_all_models(self) -> list:
        """Unloads all currently loaded model instances from LM Studio memory.
        Returns a list of unloaded instance IDs/keys.
        """
        unloaded_list = []
        try:
            loaded = self.list_models()
            models_data = loaded.get("models", []) or loaded.get("data", [])
            for m in models_data:
                model_key = m.get("key") or m.get("id")
                instances = m.get("loaded_instances", [])
                if instances:
                    for inst in instances:
                        inst_id = inst.get("id") or inst.get("instance_identifier")
                        if inst_id:
                            res = self.unload_model(model_key, instance_id=inst_id)
                            if "error" not in res:
                                unloaded_list.append(inst_id)
                else:
                    inst_id = m.get("instance_identifier") or m.get("instance_id")
                    if inst_id:
                        res = self.unload_model(model_key, instance_id=inst_id)
                        if "error" not in res:
                            unloaded_list.append(inst_id)
        except Exception:
            pass
        return unloaded_list


    def download_model(self, model_url_or_repo: str) -> Dict[str, Any]:
        """Requests downloading a model via POST /api/v1/models/download."""
        return self._request("/api/v1/models/download", method="POST", data={"model": model_url_or_repo})

    def get_download_status(self) -> Dict[str, Any]:
        """Checks the download progress via GET /api/v1/models/download/status."""
        return self._request("/api/v1/models/download/status", method="GET")

    def chat(self, model: str, message: str, context_length: Optional[int] = None) -> Dict[str, Any]:
        """Performs a stateful native chat completion request via POST /api/v1/chat."""
        self._ensure_only_model_loaded(model, load_if_missing=True)
        payload = {
            "model": model,
            "input": message
        }
        if context_length is not None:
            payload["context_length"] = context_length
        return self._request("/api/v1/chat", method="POST", data=payload)

    def chat_completions(self, model: str, messages: List[Dict[str, str]], stream: bool = False, temperature: float = 0.7, max_tokens: Optional[int] = None) -> Dict[str, Any]:
        """Performs OpenAI-compatible chat completion via POST /v1/chat/completions."""
        self._ensure_only_model_loaded(model, load_if_missing=True)
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
        self._ensure_only_model_loaded(model, load_if_missing=True)
        payload = {
            "model": model,
            "input": text_or_texts
        }
        return self._request("/v1/embeddings", method="POST", data=payload)
