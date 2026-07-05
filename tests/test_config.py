from src.config import Config


def test_process_environment_overrides_env_file_and_yaml(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "FOURTINDEX_EMBEDDING_PROVIDER_CHAIN=voyage,jina,ollama\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "embedding:\n  provider_chain:\n    - ollama\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FOURTINDEX_EMBEDDING_PROVIDER_CHAIN", "cohere,ollama")

    config = Config(str(config_path))

    assert config.embedding_provider_chain == ["cohere", "ollama"]
