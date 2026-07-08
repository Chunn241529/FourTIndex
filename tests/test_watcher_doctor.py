import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from src.config import Config
from src.llm import LLMClient
from src.watcher import CodebaseEventHandler
from src.doctor import run_diagnostics, check_http_endpoint

def test_watcher_filtering():
    """Tests that CodebaseEventHandler correctly filters out ignored files and directories."""
    callback_called = []
    def dummy_callback(paths):
        callback_called.append(paths)

    handler = CodebaseEventHandler(debounce_delay=0.1, callback=dummy_callback)

    # Mock FileSystemEvent
    class DummyEvent:
        def __init__(self, src_path, is_directory=False):
            self.src_path = src_path
            self.is_directory = is_directory

    # 1. Ignored files/directories should NOT trigger callbacks
    handler.on_any_event(DummyEvent("D:/project/FourTIndex/.git/config"))
    handler.on_any_event(DummyEvent("D:/project/FourTIndex/node_modules/package/index.js"))
    handler.on_any_event(DummyEvent("D:/project/FourTIndex/.fourtindex/db/lock"))
    handler.on_any_event(DummyEvent("D:/project/FourTIndex/src/main.py.tmp"))
    handler.on_any_event(DummyEvent("D:/project/FourTIndex/src/", is_directory=True))

    import time
    time.sleep(0.2)
    assert len(callback_called) == 0, "Callback should not be called for ignored paths"

    # 2. Valid files should trigger callbacks
    handler.on_any_event(DummyEvent("D:/project/FourTIndex/src/main.py"))
    time.sleep(0.2)
    assert len(callback_called) == 1, "Callback should be triggered for valid file modifications"
    assert "D:/project/FourTIndex/src/main.py" in callback_called[0]

@patch("src.doctor.check_http_endpoint")
def test_doctor_diagnostics(mock_check):
    """Tests that run_diagnostics evaluates health statuses correctly."""
    # Setup mock endpoints to return Online and mock model list
    mock_check.side_effect = lambda url: (True, "Online", ["monas", "text-embedding-qwen3-embedding-0.6b"])

    config = Config()
    # Temporarily set provider to lmstudio for testing
    with patch.object(Config, "llm_provider", "lmstudio"):
        with patch("sqlite3.connect") as mock_sql:
            # Mock successful registry db check
            mock_conn = MagicMock()
            mock_sql.return_value = mock_conn
            mock_conn.cursor.return_value.fetchall.return_value = [("projects",)]
            
            # Mock embedding manager/provider
            with patch("src.doctor.create_provider") as mock_create:
                mock_provider = MagicMock()
                mock_provider.embed_query.return_value = [0.1, 0.2, 0.3]
                mock_create.return_value = mock_provider

                status = run_diagnostics(config)
                assert status is True, "Diagnostics should succeed when dependencies are online"

@patch("src.token_meter.count_tokens")
def test_smart_context_guard(mock_count_tokens):
    """Tests that context guard prunes extra chunks to stay within token budget."""
    # Base prompt (non-context) = 20 tokens
    # Each chunk = 30 tokens
    # Budget = 70 tokens
    # This should accept base (20) + chunk1 (30) = 50 tokens.
    # Chunk2 (30) would exceed budget (50 + 30 = 80 > 70), so it should be pruned.
    mock_count_tokens.side_effect = lambda text, model: 20 if "--- USER QUERY ---" in text else 30

    config = Config()
    # Mock config budget
    config.data["budget"] = {"context_budget_tokens": 70}

    llm = LLMClient(config)
    llm.model = "test-model"

    # Context with two chunks
    context = "File: file1.py\n```\ncode1\n```\n\nFile: file2.py\n```\ncode2\n```"
    
    # We patch the completion call to just return the prompt used
    if llm.provider == "lmstudio":
        with patch.object(llm.lm_client, "chat_completions", return_value={"choices": [{"message": {"content": "ok"}}]}) as mock_chat:
            llm.generate_answer("query", context)
            prompt_sent = mock_chat.call_args[0][1][0]["content"]
    else:
        with patch.object(llm.client, "chat", return_value={"message": {"content": "ok"}}) as mock_chat:
            llm.generate_answer("query", context)
            prompt_sent = mock_chat.call_args[1]["messages"][0]["content"]

    # Verify that only the first chunk is in the final prompt sent to LLM
    assert "file1.py" in prompt_sent, "First chunk should be preserved"
    assert "file2.py" not in prompt_sent, "Second chunk should be pruned due to budget limit"
