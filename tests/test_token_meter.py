import json

from src import token_meter


def _write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def test_parse_codex_uses_exact_usage_and_model(tmp_path):
    transcript = tmp_path / "codex.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "session_meta",
                "payload": {"session_id": "codex-session"},
            },
            {"type": "turn_context", "payload": {"model": "gpt-5.5"}},
            {
                "type": "response_item",
                "payload": {"type": "custom_tool_call"},
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 120,
                            "output_tokens": 30,
                            "total_tokens": 150,
                        },
                        "last_token_usage": {
                            "input_tokens": 20,
                            "output_tokens": 5,
                            "total_tokens": 44,
                        },
                        "model_context_window": 200000,
                    },
                },
            },
        ],
    )

    usage = token_meter.parse_codex_transcript(str(transcript), "fallback")

    assert usage.agent == "codex"
    assert usage.model == "gpt-5.5"
    assert usage.conversation_id == "codex-session"
    assert (usage.total_prompt, usage.total_completion) == (120, 30)
    assert (usage.turn_prompt, usage.turn_completion) == (20, 5)
    assert usage.active_context_tokens == 44
    assert usage.guard_context_tokens == 44
    assert usage.displayed_context_tokens == 44
    assert usage.model_context_window == 200000
    assert usage.total_tool_calls == 1


def test_parse_claude_sums_usage_and_tools(tmp_path):
    transcript = tmp_path / "claude.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "assistant",
                "message": {
                    "model": "claude-sonnet-4.6",
                    "usage": {
                        "input_tokens": 10,
                        "cache_read_input_tokens": 4,
                        "output_tokens": 3,
                    },
                    "content": [{"type": "tool_use"}],
                },
            },
            {
                "type": "assistant",
                "message": {
                    "model": "claude-sonnet-4.6",
                    "usage": {"input_tokens": 20, "output_tokens": 6},
                    "content": [],
                },
            },
        ],
    )

    usage = token_meter.parse_claude_transcript(str(transcript), "claude-session")

    assert usage.agent == "claude"
    assert usage.model == "claude-sonnet-4.6"
    assert (usage.total_prompt, usage.total_completion) == (34, 9)
    assert (usage.turn_prompt, usage.turn_completion) == (20, 6)
    assert usage.total_tool_calls == 1


def test_latest_session_is_selected_across_adapters(monkeypatch):
    older = token_meter.SessionCandidate("claude", "old", "old", 1, None)
    newer = token_meter.SessionCandidate("codex", "new", "new", 2, None)
    monkeypatch.setattr(
        token_meter,
        "SESSION_DISCOVERERS",
        (lambda: [older], lambda: [newer]),
    )

    assert token_meter.get_latest_conversation_log() == newer


def test_codex_subagent_sessions_are_excluded(tmp_path, monkeypatch):
    primary = tmp_path / "primary.jsonl"
    reviewer = tmp_path / "reviewer.jsonl"
    _write_jsonl(
        primary,
        [{"type": "session_meta", "payload": {"source": "vscode"}}],
    )
    _write_jsonl(
        reviewer,
        [
            {
                "type": "session_meta",
                "payload": {"source": {"subagent": "auto-review"}},
            }
        ],
    )
    monkeypatch.setattr(
        token_meter.glob,
        "glob",
        lambda *_args, **_kwargs: [str(primary), str(reviewer)],
    )

    sessions = token_meter.discover_codex_sessions()

    assert [session.path for session in sessions] == [str(primary)]


def test_parse_antigravity_transcript_ignoring_history(tmp_path):
    transcript = tmp_path / "antigravity.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "USER_INPUT",
                "source": "USER_EXPLICIT",
                "content": "Hello",
            },
            {
                "type": "CONVERSATION_HISTORY",
                "source": "SYSTEM",
                "content": "A very large conversation history",
            },
            {
                "type": "PLANNER_RESPONSE",
                "source": "MODEL",
                "content": "Model response",
            },
            {
                "type": "VIEW_FILE",
                "source": "MODEL",
                "content": "File content that is long",
            },
        ],
    )

    usage = token_meter.parse_antigravity_transcript(str(transcript), "test-session")

    assert usage.agent == "antigravity"
    # "Hello" (5 chars / 4 = 1 token) + "File content that is long" (25 chars / 4 = 6 tokens) = 7 tokens for prompt.
    # Note: "A very large conversation history" is ignored.
    assert usage.total_prompt == 7
    # "Model response" (14 chars / 4 = 3 tokens) = 3 tokens for completion.
    assert usage.total_completion == 3
