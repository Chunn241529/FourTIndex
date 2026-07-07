import sys
from unittest.mock import MagicMock

# Mock sys.modules for sentence_transformers so tests run without installing it
mock_st = MagicMock()
sys.modules['sentence_transformers'] = mock_st

from src.config import Config
from src.reranker import LocalReranker

def test_local_reranker(tmp_path):
    class MockCrossEncoder:
        def __init__(self, model_name):
            self.model_name = model_name

        def predict(self, pairs):
            scores = []
            for query, doc in pairs:
                if "relevant" in doc.lower():
                    scores.append(0.9)
                elif "secondary" in doc.lower():
                    scores.append(0.5)
                else:
                    scores.append(0.1)
            return scores

    mock_st.CrossEncoder = MockCrossEncoder

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "rerank:\n"
        "  enabled: true\n"
        "  model: \"test-model\"\n"
        "  candidates_limit: 10\n",
        encoding="utf-8"
    )
    config = Config(str(config_path))
    
    reranker = LocalReranker(config)
    
    chunks = [
        {"content": "this is some spam data", "metadata": {"file_path": "spam.txt"}},
        {"content": "this is secondary content", "metadata": {"file_path": "sec.txt"}},
        {"content": "this is very relevant content", "metadata": {"file_path": "rel.txt"}},
    ]
    
    results = reranker.rerank("relevant query", chunks, top_k=2)
    
    assert len(results) == 2
    assert results[0]["metadata"]["file_path"] == "rel.txt"
    assert results[0]["rerank_score"] == 0.9
    assert results[1]["metadata"]["file_path"] == "sec.txt"
    assert results[1]["rerank_score"] == 0.5

