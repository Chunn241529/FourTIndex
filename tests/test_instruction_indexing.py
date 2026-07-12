from src.config import Config
from src.indexer import Indexer


def test_scan_files_includes_hidden_agent_instructions(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  name: instructions-test",
                "  exclude_dirs: [.git, .agents]",
                "  supported_extensions: [.py, .md]",
                "  max_file_size_bytes: 2097152",
                "  respect_gitignore: true",
                "database:",
                f"  persist_directory: '{(tmp_path / 'state' / 'db').as_posix()}'",
            ]
        ),
        encoding="utf-8",
    )
    agents_root = tmp_path / ".agents"
    skill_root = agents_root / "skills" / "Example"
    skill_root.mkdir(parents=True)
    agents_file = agents_root / "AGENTS.md"
    skill_file = skill_root / "SKILL.md"
    agents_file.write_text("# Agent rules", encoding="utf-8")
    skill_file.write_text("---\nname: Example\n---\n# Example", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".agents/\n", encoding="utf-8")

    files = {path.replace("\\", "/") for path in Indexer(Config(str(config_path))).scan_files(str(tmp_path))}

    assert str(agents_file).replace("\\", "/") in files
    assert str(skill_file).replace("\\", "/") in files
