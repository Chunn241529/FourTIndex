import json
import logging
import threading
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional
from src.config import Config

class LMStudioClient:
    _model_lock = threading.RLock()

    def __init__(self, config: Config):
        self.config = config
        self.host = self.config.lmstudio_host
        self.api_token = self.config.lmstudio_api_token

    def _request(
        self,
        path: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        timeout: float = 30,
    ) -> Dict[str, Any]:
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
            with urllib.request.urlopen(req, timeout=timeout) as response:
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

    @staticmethod
    def _model_matches(model_key: str, requested: str) -> bool:
        return model_key == requested or model_key == f"text-embedding-{requested}"

    def _is_large_model(self, model_data: Dict[str, Any]) -> bool:
        try:
            size_bytes = int(model_data.get("size_bytes"))
        except (TypeError, ValueError):
            return True
        return size_bytes >= self.config.lmstudio_large_model_threshold_bytes

    def _companion_priority(self, model_key: str) -> tuple[int, str]:
        embedding = self.config.lmstudio_embedding_model
        reranker = self.config.rerank_model
        if self._model_matches(model_key, embedding):
            return (0, model_key)
        if self._model_matches(model_key, reranker):
            return (1, model_key)
        return (2, model_key)

    @staticmethod
    def _loaded_instances(model_data: Dict[str, Any]) -> list[str]:
        instances = model_data.get("loaded_instances", [])
        if instances:
            return [
                instance_id
                for instance in instances
                if (instance_id := instance.get("id") or instance.get("instance_identifier"))
            ]
        instance_id = model_data.get("instance_identifier") or model_data.get("instance_id")
        return [instance_id] if instance_id else []

    def _ensure_model_policy(self, model: str, load_if_missing: bool = True) -> bool:
        inventory = self.list_models()
        if "error" in inventory:
            raise RuntimeError(f"Unable to inspect LM Studio models: {inventory['error']}")
        models = inventory.get("models", []) or inventory.get("data", [])
        target_data = next(
            (
                item
                for item in models
                if self._model_matches(item.get("key") or item.get("id") or "", model)
            ),
            {"key": model},
        )
        target_key = target_data.get("key") or target_data.get("id") or model
        target_is_large = self._is_large_model(target_data)

        loaded = []
        for item in models:
            key = item.get("key") or item.get("id") or ""
            for instance_id in self._loaded_instances(item):
                loaded.append(
                    {
                        "key": key,
                        "instance_id": instance_id,
                        "large": self._is_large_model(item),
                        "target": self._model_matches(key, model),
                    }
                )

        target_instances = [item for item in loaded if item["target"]]
        keep_instance_ids = {
            target_instances[0]["instance_id"]
        } if target_instances else set()
        non_targets = [item for item in loaded if not item["target"]]
        if target_is_large:
            small = sorted(
                (item for item in non_targets if not item["large"]),
                key=lambda item: self._companion_priority(item["key"]),
            )
            if small:
                keep_instance_ids.add(small[0]["instance_id"])
        else:
            large = sorted(
                (item for item in non_targets if item["large"]),
                key=lambda item: (0 if self._model_matches(item["key"], self.config.lmstudio_llm_model) else 1, item["key"]),
            )
            if large:
                keep_instance_ids.add(large[0]["instance_id"])
            else:
                small = sorted(
                    (item for item in non_targets if not item["large"]),
                    key=lambda item: self._companion_priority(item["key"]),
                )
                if small:
                    keep_instance_ids.add(small[0]["instance_id"])

        for item in loaded:
            if item["instance_id"] in keep_instance_ids:
                continue
            response = self.unload_model(item["key"], instance_id=item["instance_id"])
            if "error" in response:
                raise RuntimeError(
                    f"Unable to unload conflicting model '{item['key']}': {response['error']}"
                )

        if not target_instances and load_if_missing:
            response = self._request(
                "/api/v1/models/load", method="POST", data={"model": model}
            )
            if "error" in response:
                raise RuntimeError(f"Unable to load model '{target_key}': {response['error']}")
        return bool(target_instances)

    def _ensure_only_model_loaded(self, model: str, load_if_missing: bool = True) -> None:
        """Backward-compatible entry point for enforcing the model capacity policy."""
        with self._model_lock:
            self._ensure_model_policy(model, load_if_missing)

    def load_model(self, model: str, context_length: Optional[int] = None, extra_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Loads a model into memory via POST /api/v1/models/load."""
        try:
            with self._model_lock:
                already_loaded = self._ensure_model_policy(model, load_if_missing=False)
                if already_loaded:
                    return {"success": True, "already_loaded": True}
                payload = {"model": model}
                if context_length is not None:
                    payload["context_length"] = context_length
                if extra_config:
                    payload.update(extra_config)
                response = self._request(
                    "/api/v1/models/load", method="POST", data=payload
                )
                if "error" not in response:
                    return response

                inventory = self.list_models()
                model_data = next(
                    (
                        item
                        for item in inventory.get("models", [])
                        if self._model_matches(
                            item.get("key") or item.get("id") or "", model
                        )
                    ),
                    None,
                )
                if model_data and model_data.get("type") == "llm":
                    fallback = self._request(
                        "/api/v1/chat",
                        method="POST",
                        data={"model": model, "input": ""},
                    )
                    if "error" not in fallback:
                        return {"success": True, "fallback": "chat_auto_load"}
                return response
        except Exception as exc:
            logging.getLogger("fourTindex.lmstudio_client").error(str(exc))
            return {"error": str(exc)}

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
        with self._model_lock:
            self._ensure_model_policy(model, load_if_missing=False)
            payload = {"model": model, "input": message}
            if context_length is not None:
                payload["context_length"] = context_length
            return self._request("/api/v1/chat", method="POST", data=payload)

    def chat_completions(self, model: str, messages: List[Dict[str, str]], stream: bool = False, temperature: float = 0.7, max_tokens: Optional[int] = None) -> Dict[str, Any]:
        """Performs OpenAI-compatible chat completion via POST /v1/chat/completions."""
        return self._chat_completions(
            model, messages, stream, temperature, max_tokens, timeout=30
        )

    def _chat_completions(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream: bool,
        temperature: float,
        max_tokens: Optional[int],
        timeout: float,
    ) -> Dict[str, Any]:
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        with self._model_lock:
            self._ensure_model_policy(model, load_if_missing=False)
            return self._request(
                "/v1/chat/completions", method="POST", data=payload, timeout=timeout
            )

    def embeddings(self, model: str, text_or_texts: Any) -> Dict[str, Any]:
        """Performs OpenAI-compatible embedding generation via POST /v1/embeddings."""
        with self._model_lock:
            self._ensure_model_policy(model, load_if_missing=False)
            payload = {"model": model, "input": text_or_texts}
            return self._request("/v1/embeddings", method="POST", data=payload)
