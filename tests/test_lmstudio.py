import json
from unittest.mock import MagicMock, patch
import pytest
from src.config import Config
from src.lmstudio_client import LMStudioClient
from src.llm import LLMClient
from src.embedder import Embedder

def mock_urlopen_success(req, timeout=None):
    url = req.full_url if hasattr(req, 'full_url') else req
    data = req.data.decode('utf-8') if hasattr(req, 'data') and req.data else ""
    
    response_data = {}
    if "/api/v1/models/load" in url:
        response_data = {"success": True, "message": "Loaded successfully"}
    elif "/api/v1/models/unload" in url:
        response_data = {"success": True, "message": "Unloaded successfully"}
    elif "/api/v1/models/download/status" in url:
        response_data = {"progress": 100, "status": "completed"}
    elif "/api/v1/models/download" in url:
        response_data = {"success": True, "message": "Downloading"}
    elif "/api/v1/models" in url:
        response_data = {"data": [{"id": "qwen2.5-coder-7b", "object": "model"}]}
    elif "/api/v1/chat" in url:
        response_data = {"content": "Native chat response"}
    elif "/v1/chat/completions" in url:
        response_data = {
            "choices": [{"message": {"content": "Hello from LM Studio completions"}}]
        }
    elif "/v1/embeddings" in url:
        # Mock single vs batch
        if data and '"input": [' in data:
            response_data = {
                "data": [
                    {"embedding": [0.1, 0.2], "index": 0},
                    {"embedding": [0.3, 0.4], "index": 1}
                ]
            }
        else:
            response_data = {
                "data": [{"embedding": [0.1, 0.2], "index": 0}]
            }
            
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response_data).encode("utf-8")
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    return mock_resp

@patch("urllib.request.urlopen", side_effect=mock_urlopen_success)
def test_lmstudio_client_endpoints(mock_url, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("provider: \"lmstudio\"\n", encoding="utf-8")
    config = Config(str(config_path))
    client = LMStudioClient(config)
    
    # 1. List
    res = client.list_models()
    assert "data" in res
    assert res["data"][0]["id"] == "qwen2.5-coder-7b"
    
    # 2. Load
    res = client.load_model("qwen2.5-coder-7b")
    assert res["success"] is True
    
    # 3. Unload
    res = client.unload_model("qwen2.5-coder-7b")
    assert res["success"] is True
    
    # 4. Download
    res = client.download_model("some/repo")
    assert res["success"] is True
    
    # 5. Status
    res = client.get_download_status()
    assert res["status"] == "completed"
    
    # 6. Chat Native
    res = client.chat("qwen2.5-coder-7b", "Hi")
    assert res["content"] == "Native chat response"
    
    # 7. OpenAI chat completion
    res = client.chat_completions("qwen2.5-coder-7b", [{"role": "user", "content": "Hi"}])
    assert res["choices"][0]["message"]["content"] == "Hello from LM Studio completions"

@patch("urllib.request.urlopen", side_effect=mock_urlopen_success)
def test_llm_client_integration(mock_url, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("provider: \"lmstudio\"\n", encoding="utf-8")
    config = Config(str(config_path))
    
    llm = LLMClient(config)
    ans = llm.generate_answer("Hi", "context")
    assert ans == "Hello from LM Studio completions"

@patch("urllib.request.urlopen", side_effect=mock_urlopen_success)
def test_embedder_integration(mock_url, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("provider: \"lmstudio\"\n", encoding="utf-8")
    config = Config(str(config_path))
    
    embedder = Embedder(config)
    
    # Single embedding
    emb = embedder.get_embedding("hello")
    assert emb == [0.1, 0.2]
    
    # Batch embedding
    embs = embedder.get_embeddings_batch(["hello", "world"])
    assert embs == [[0.1, 0.2], [0.3, 0.4]]

@patch("urllib.request.urlopen", side_effect=mock_urlopen_success)
def test_lmstudio_setup(mock_url, tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "provider: \"ollama\"\n"
        "lmstudio:\n"
        "  host: \"http://127.0.0.1:2401\"\n"
        "  llm_model: \"monas\"\n"
        "  embedding_model: \"text-embedding-qwen3-embedding-0.6b\"\n",
        encoding="utf-8"
    )
    
    def mock_urlopen_setup(req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else req
        response_data = {}
        if "/api/v1/models/load" in url:
            response_data = {"success": True}
        elif "/api/v1/models" in url:
            response_data = {
                "data": [
                    {"id": "monas", "object": "model"},
                    {"id": "text-embedding-qwen3-embedding-0.6b", "object": "model"}
                ]
            }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode("utf-8")
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen_setup):
        monkeypatch.setenv("FOURTINDEX_CONFIG_PATH", str(config_path))
        from src.setup_lmstudio import run_setup
        success = run_setup()
        assert success is True
        
        import yaml
        with open(str(config_path), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["provider"] == "lmstudio"

