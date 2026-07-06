import json
import os
from src import context_auditor
from src.config import Config

def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

def test_audit_antigravity_session(tmp_path):
    log_file = tmp_path / "transcript_full.jsonl"
    records = [
        {
            "type": "USER_INPUT",
            "source": "USER_EXPLICIT",
            "created_at": "2026-07-06T02:00:00Z",
            "content": "<USER_REQUEST>Test Query</USER_REQUEST>"
        },
        {
            "type": "PLANNER_RESPONSE",
            "source": "MODEL",
            "content": "Model Response Text",
            "thinking": "Thinking process",
            "tool_calls": [
                {
                    "name": "view_file",
                    "args": {"TargetFile": "d:/project/FourTIndex/src/config.py"}
                }
            ]
        },
        {
            "type": "VIEW_FILE",
            "source": "SYSTEM",
            "content": "File Path: `file:///d:/project/FourTIndex/src/config.py`\nCode line content here"
        }
    ]
    _write_jsonl(log_file, records)

    data = context_auditor.audit_antigravity_session(str(log_file), "test-conv-id")
    
    assert data["agent"] == "antigravity"
    assert data["conversation_id"] == "test-conv-id"
    assert len(data["turns"]) == 1
    
    turn = data["turns"][0]
    assert turn["full_query"] == "Test Query"
    assert "view_file" in turn["tool_calls"]
    assert len(turn["files_read"]) == 1
    assert turn["files_read"][0]["name"] == "config.py"
    assert "config.py" in data["modified_files"] or len(data["modified_files"]) == 0

def test_get_recommendations():
    turns = [
        {
            "turn_index": 1,
            "prompt_tokens": 50000,
            "completion_tokens": 1000,
            "cost": 0.08,
            "files_read": [
                {"name": "large.py", "tokens": 15000}
            ],
            "tool_details": [
                {"name": "run_command", "tokens": 20000}
            ]
        }
    ]
    
    recs = context_auditor.get_recommendations(turns)
    
    # It should have warning about total context size, stale large files, and tool outputs
    messages = [r["message"] for r in recs]
    assert any("context is very large" in m for m in messages)
    assert any("large.py" in m for m in messages)
    assert any("run_command" in m for m in messages)

def test_generate_local_bridge():
    audit_data = {
        "agent": "antigravity",
        "model": "gemini-3.5-flash",
        "modified_files": ["config.py", "main.py"],
        "user_prompts": ["Query 1", "Query 2"]
    }
    config = Config()
    bridge = context_auditor.generate_local_bridge(audit_data, config, use_llm=False)
    
    assert "Query 2" in bridge
    assert "config.py" in bridge
    assert "main.py" in bridge
