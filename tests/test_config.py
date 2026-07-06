from src.config import Config


def test_embedding_provider_chain_ignores_external_configuration(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "embedding:\n  provider_chain:\n    - remote\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FOURTINDEX_EMBEDDING_PROVIDER_CHAIN", "remote,ollama")

    config = Config(str(config_path))

    assert config.embedding_provider_chain == ["ollama"]
