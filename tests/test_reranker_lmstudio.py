import json
from types import SimpleNamespace

from src.reranker import LocalReranker


def reranker_with_output(output):
    reranker = object.__new__(LocalReranker)
    reranker.model_name = "reranker"
    reranker.lm_client = SimpleNamespace(
        _chat_completions=lambda **kwargs: {
            "choices": [{"message": {"content": output}}]
        }
    )
    return reranker


def candidates():
    return [
        {"content": "first", "metadata": {"file_path": "a.py"}},
        {"content": "second", "metadata": {"file_path": "b.py"}},
        {"content": "third", "metadata": {"file_path": "c.py"}},
    ]


def test_lmstudio_reranker_batches_and_sorts_valid_json():
    output = json.dumps(
        [
            {"index": 0, "score": 0.2},
            {"index": 1, "score": 0.9},
            {"index": 2, "score": 0.5},
        ]
    )
    result = reranker_with_output(output)._rerank_via_lmstudio(
        "query", candidates(), top_k=2
    )
    assert [item["content"] for item in result] == ["second", "third"]


def test_lmstudio_reranker_rejects_invalid_outputs_and_preserves_order():
    invalid_outputs = [
        "0.85 Human: Query: split",
        json.dumps([{"index": 0, "score": 0.5}]),
        json.dumps(
            [
                {"index": 0, "score": 0.5},
                {"index": 0, "score": 0.4},
                {"index": 2, "score": 2.0},
            ]
        ),
    ]
    for output in invalid_outputs:
        source = candidates()
        result = reranker_with_output(output)._rerank_via_lmstudio(
            "query", source, top_k=2
        )
        assert result == source[:2]
        assert all("rerank_score" not in item for item in result)
