import threading
from types import SimpleNamespace

from src.lmstudio_client import LMStudioClient


GIB = 1024**3


class StatefulLMStudioClient(LMStudioClient):
    def __init__(self, models, fail_unload=False):
        self.config = SimpleNamespace(
            lmstudio_large_model_threshold_bytes=2 * GIB,
            lmstudio_embedding_model="embed",
            lmstudio_llm_model="large-a",
            rerank_model="reranker",
        )
        self.models = models
        self.fail_unload = fail_unload

    def list_models(self):
        return {"models": self.models}

    def _request(self, path, method="GET", data=None, timeout=30):
        if path.endswith("/unload"):
            if self.fail_unload:
                return {"error": "unload failed"}
            instance_id = data["instance_id"]
            for model in self.models:
                model["loaded_instances"] = [
                    item
                    for item in model.get("loaded_instances", [])
                    if item.get("id") != instance_id
                ]
            return {"success": True}
        if path.endswith("/load"):
            requested = data["model"]
            model = next(
                item
                for item in self.models
                if self._model_matches(item["key"], requested)
            )
            model.setdefault("loaded_instances", []).append({"id": model["key"]})
            return {"success": True}
        return {"success": True}


def model(key, size_gib=None, loaded=False, instances=1):
    item = {"key": key, "loaded_instances": []}
    if size_gib is not None:
        item["size_bytes"] = int(size_gib * GIB)
    if loaded:
        item["loaded_instances"] = [
            {"id": f"{key}-{index}"} for index in range(instances)
        ]
    return item


def loaded_keys(client):
    return {
        item["key"]
        for item in client.models
        if item.get("loaded_instances")
    }


def assert_capacity(client):
    loaded = [item for item in client.models if item.get("loaded_instances")]
    large = [item for item in loaded if client._is_large_model(item)]
    small = [item for item in loaded if not client._is_large_model(item)]
    assert len(loaded) <= 2
    assert len(large) <= 1
    assert len(small) <= 2


def test_small_request_keeps_large_and_replaces_small():
    client = StatefulLMStudioClient(
        [model("large-a", 8, True), model("embed", 1, True), model("reranker", 0.6)]
    )
    assert "error" not in client.load_model("reranker")
    assert loaded_keys(client) == {"large-a", "reranker"}
    assert_capacity(client)


def test_two_small_models_can_remain_loaded_without_large():
    client = StatefulLMStudioClient(
        [model("embed", 1, True), model("reranker", 0.6), model("small-c", 0.5)]
    )
    assert "error" not in client.load_model("small-c")
    assert loaded_keys(client) == {"embed", "small-c"}
    assert_capacity(client)


def test_large_request_replaces_large_and_keeps_one_small():
    client = StatefulLMStudioClient(
        [model("large-a", 8, True), model("large-b", 4), model("embed", 1, True)]
    )
    assert "error" not in client.load_model("large-b")
    assert loaded_keys(client) == {"large-b", "embed"}
    assert_capacity(client)


def test_unknown_size_is_large_and_duplicate_target_instances_are_removed():
    client = StatefulLMStudioClient(
        [model("large-a", 8, True), model("unknown", None, True, instances=2)]
    )
    client._ensure_only_model_loaded("unknown", load_if_missing=False)
    assert loaded_keys(client) == {"unknown"}
    assert len(client.models[1]["loaded_instances"]) == 1
    assert_capacity(client)


def test_policy_failure_is_returned_and_concurrent_loads_remain_bounded():
    failing = StatefulLMStudioClient(
        [model("large-a", 8, True), model("large-b", 4)], fail_unload=True
    )
    assert "error" in failing.load_model("large-b")

    client = StatefulLMStudioClient(
        [model("large-a", 8), model("large-b", 4), model("embed", 1), model("reranker", 0.6)]
    )
    threads = [
        threading.Thread(target=client.load_model, args=(name,))
        for name in ("large-a", "embed", "large-b", "reranker")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert_capacity(client)
