import os
import json
import pytest
import datetime
from pathlib import Path

from src import mcp_server
from src.config import Config
from src.database import Database
from src.embedder import Embedder
from src.indexer import Indexer
from src.project_identity import ProjectResolver
from tests.test_indexing_service import FakeProvider


@pytest.fixture(autouse=True)
def setup_test_mcp_context(tmp_path, monkeypatch):
    # Setup temporary config
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join([
            "project:",
            "  name: FourTIndex",
            "  exclude_dirs: [.git, .fourtindex]",
            "  supported_extensions: [.py, .md]",
            "database:",
            f"  persist_directory: '{(tmp_path / 'state' / 'db').as_posix()}'",
            "embedding:",
            "  provider_chain: [ollama]",
            "indexing:",
            "  parse_workers: 1",
            "  commit_batch_files: 32",
            "  max_file_size_bytes: 2097152",
            "  respect_gitignore: true",
            "rerank:",
            "  enabled: false"
        ]),
        encoding="utf-8"
    )
    test_config = Config(str(config_path))
    
    test_db = Database(test_config)
    test_embedder = Embedder(test_config)
    fake_provider = FakeProvider()
    monkeypatch.setattr(FakeProvider, "_vector", lambda *args: [1.0, 0.0, 0.0])
    
    # Mock class-level EmbeddingManager methods to set self.provider and return FakeProvider
    from src.embedding.manager import EmbeddingManager
    monkeypatch.setattr(EmbeddingManager, "select_for_new_index", lambda self, requested="auto": setattr(self, "provider", fake_provider) or fake_provider)
    monkeypatch.setattr(EmbeddingManager, "load_profile", lambda self, profile: setattr(self, "provider", fake_provider) or fake_provider)
    
    monkeypatch.setattr(test_embedder, "provider", "fake")
    monkeypatch.setattr(test_embedder, "model", "fake-model")
    monkeypatch.setattr(test_embedder, "get_embedding", lambda text: fake_provider.embed_query(text))
    monkeypatch.setattr(test_embedder, "get_embeddings_batch", lambda texts: fake_provider.embed_documents(texts))
    
    test_indexer = Indexer(test_config)
    
    monkeypatch.setattr(mcp_server, "config", test_config)
    monkeypatch.setattr(mcp_server, "db", test_db)
    monkeypatch.setattr(mcp_server, "embedder", test_embedder)
    monkeypatch.setattr(mcp_server, "indexer", test_indexer)
    monkeypatch.setattr(
        mcp_server,
        "project_resolver",
        ProjectResolver(
            str(tmp_path / "project_registry.json"),
            str(tmp_path / "state" / "index_manifest.json"),
        ),
    )
    
    # Initialize error log for each test
    monkeypatch.setattr(mcp_server, "_recent_errors", [])
    
    return test_config, test_db, test_embedder, test_indexer


def test_mcp_index_and_search_codebase(tmp_path):
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    
    py_file = project_dir / "app.py"
    py_file.write_text("def hello():\n    print('Hello World')\n", encoding="utf-8")
    
    mcp_server.db.save_project_path("FourTIndex", str(project_dir))
    
    # Test index_project
    res = mcp_server.index_project(str(project_dir), "FourTIndex")
    assert "Indexed 1 files" in res or "indexed=1" in res
    
    # Test index_project JSON mode
    res_json = mcp_server.index_project(str(project_dir), "FourTIndex", output_json=True)
    res_data = json.loads(res_json)
    assert res_data["success"] is True
    assert res_data["scanned"] == 1
    
    # Test search_codebase text mode
    search_res = mcp_server.search_codebase("hello print", "FourTIndex")
    assert "app.py" in search_res
    assert "Freshness:" in search_res
    
    # Test search_codebase JSON mode
    search_res_json = mcp_server.search_codebase("hello print", "FourTIndex", output_json=True)
    search_data = json.loads(search_res_json)
    assert len(search_data) > 0
    assert search_data[0]["file_path"] == "app.py"
    assert search_data[0]["stale"] is False
    assert "indexed_at" in search_data[0]
    assert "source_hash" in search_data[0]
    
    # Modify file to make it stale
    py_file.write_text("def hello():\n    print('Hello World Updated')\n", encoding="utf-8")
    mcp_server._query_cache.clear()
    search_res_json_stale = mcp_server.search_codebase("hello print", "FourTIndex", output_json=True)
    search_data_stale = json.loads(search_res_json_stale)
    assert search_data_stale[0]["stale"] is True


def test_mcp_outline_and_details(tmp_path):
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    py_file = project_dir / "app.py"
    py_file.write_text("class Greeting:\n    def say_hi(self):\n        pass\n", encoding="utf-8")
    
    mcp_server.db.save_project_path("FourTIndex", str(project_dir))
    mcp_server.index_project(str(project_dir), "FourTIndex")
    
    # get_file_outline
    outline = mcp_server.get_file_outline("app.py", "FourTIndex")
    assert "Greeting" in outline
    
    outline_json = mcp_server.get_file_outline("app.py", "FourTIndex", output_json=True)
    outline_data = json.loads(outline_json)
    assert outline_data["file_path"] == "app.py"
    assert "Greeting" in outline_data["outline"]
    
    # get_symbol_definition
    defn = mcp_server.get_symbol_definition("Greeting.say_hi", "FourTIndex")
    assert "say_hi" in defn
    
    defn_json = mcp_server.get_symbol_definition("Greeting.say_hi", "FourTIndex", output_json=True)
    defn_data = json.loads(defn_json)
    assert defn_data["symbol_name"] == "Greeting.say_hi"
    assert "say_hi" in defn_data["definition"]
    
    # read_code_lines
    lines = mcp_server.read_code_lines("app.py", 1, 3, "FourTIndex")
    assert "Greeting" in lines
    
    lines_json = mcp_server.read_code_lines("app.py", 1, 3, "FourTIndex", output_json=True)
    lines_data = json.loads(lines_json)
    assert lines_data["file_path"] == "app.py"
    assert "Greeting" in lines_data["content"]
    assert len(lines_data["lines"]) == 3


def test_mcp_sessions(tmp_path):
    mcp_server.save_session_summary("session_001", "Design: we implemented the core auth modules.", "FourTIndex")
    
    # Test search session summaries
    res = mcp_server.search_session_summaries("auth modules", "FourTIndex")
    assert "session_001" in res
    assert "core auth" in res
    
    # JSON mode
    res_json = mcp_server.search_session_summaries("auth modules", "FourTIndex", output_json=True)
    data = json.loads(res_json)
    assert len(data) > 0
    assert data[0]["id"] == "session_001"
    assert "auth modules" in data[0]["content"]


def test_mcp_skills(tmp_path):
    skill_dir = tmp_path / "skills" / "MySkill"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\nname: MySkill\ndescription: Custom coding instructions\n---\n"
        "# Custom coding instructions\n\n## Section A\nAlways write comments.\n",
        encoding="utf-8"
    )
    
    # Register project path pointing to skill_dir.parent to allow resolving
    mcp_server.db.save_project_path("FourTIndex", str(skill_dir.parent))
    
    # index_skill
    res = mcp_server.index_skill(str(skill_file), "FourTIndex")
    assert "Successfully indexed skill" in res
    
    # list_skills
    skills = mcp_server.list_skills()
    assert "MySkill" in skills
    assert "[STALE]" not in skills
    
    skills_json = mcp_server.list_skills(output_json=True)
    skills_data = json.loads(skills_json)
    assert len(skills_data) == 1
    assert skills_data[0]["skill_name"] == "MySkill"
    assert skills_data[0]["stale"] is False
    
    # get_skill_outline
    outline = mcp_server.get_skill_outline("MySkill", "FourTIndex")
    assert "Section A" in outline
    
    # read_skill_section
    sec = mcp_server.read_skill_section("MySkill", "Section A", "FourTIndex")
    assert "Always write comments" in sec
    
    # search_skills
    search_res = mcp_server.search_skills("comments", "FourTIndex")
    assert "MySkill" in search_res
    
    # Modify skill file to trigger staleness warning
    skill_file.write_text("Modified content", encoding="utf-8")
    
    # check outline again
    outline_stale = mcp_server.get_skill_outline("MySkill", "FourTIndex")
    assert "stale" in outline_stale.lower()
    
    # check search_skills stale JSON
    search_res_json = mcp_server.search_skills("comments", "FourTIndex", output_json=True)
    search_data = json.loads(search_res_json)
    assert search_data["warning"] != ""
    assert "stale" in search_data["warning"].lower()


def test_mcp_syntax_checks(tmp_path):
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    
    # Create 3 Python files
    (project_dir / "valid1.py").write_text("def ok():\n    pass\n", encoding="utf-8")
    (project_dir / "valid2.py").write_text("x = 42\n", encoding="utf-8")
    (project_dir / "invalid.py").write_text("def broken(\n", encoding="utf-8")
    
    mcp_server.db.save_project_path("FourTIndex", str(project_dir))
    
    # check_syntax single file ok
    res_ok = mcp_server.check_syntax("valid1.py", "FourTIndex")
    assert "No syntax errors found" in res_ok
    
    # check_syntax single file broken
    res_err = mcp_server.check_syntax("invalid.py", "FourTIndex")
    assert "broken" in res_err or "Syntax Error" in res_err
    
    # check_syntax directory scan with max_files limit
    res_dir = mcp_server.check_syntax(".", "FourTIndex", max_files=2)
    assert "Checked 2 file(s)" in res_dir
    assert "trunc" in res_dir.lower() or "limit" in res_dir.lower()
    
    # check_syntax JSON mode
    res_json = mcp_server.check_syntax(".", "FourTIndex", max_files=2, output_json=True)
    data = json.loads(res_json)
    assert data["truncated"] is True
    assert data["checked_count"] == 2
    assert "invalid.py" in data["errors"] or len(data["errors"]) > 0


def test_diff_index_status(tmp_path):
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    (project_dir / "a.py").write_text("def a(): pass\n", encoding="utf-8")
    (project_dir / "b.py").write_text("def b(): pass\n", encoding="utf-8")
    
    mcp_server.db.save_project_path("FourTIndex", str(project_dir))
    
    # diff before indexing -> all new
    diff_res = mcp_server.diff_index_status("FourTIndex")
    assert "New files:      2" in diff_res
    
    # Index project
    mcp_server.index_project(str(project_dir), "FourTIndex")
    
    # diff after indexing -> up to date
    diff_res2 = mcp_server.diff_index_status("FourTIndex")
    assert "Index is completely up-to-date" in diff_res2
    
    # Modify a.py, delete b.py, add c.py
    (project_dir / "a.py").write_text("def a(): pass # updated\n", encoding="utf-8")
    (project_dir / "b.py").unlink()
    (project_dir / "c.py").write_text("def c(): pass\n", encoding="utf-8")
    
    # diff again
    diff_res3 = mcp_server.diff_index_status("FourTIndex", output_json=True)
    diff_data = json.loads(diff_res3)
    assert diff_data["new_count"] == 1
    assert "c.py" in diff_data["new_files"]
    assert diff_data["stale_count"] == 1
    assert "a.py" in diff_data["stale_files"]
    assert diff_data["deleted_count"] == 1
    assert "b.py" in diff_data["deleted_files"]


def test_framework_detection_and_roadmap(tmp_path):
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    
    # Add python files
    (project_dir / "manage.py").write_text("# Django entrypoint\n", encoding="utf-8")
    (project_dir / "pyproject.toml").write_text(
        "[tool.poetry.dependencies]\npython = \"^3.10\"\nfastapi = \"^0.95.0\"\npytest = \"*\"\n",
        encoding="utf-8"
    )
    
    mcp_server.db.save_project_path("FourTIndex", str(project_dir))
    
    # Index project to generate roadmap
    mcp_server.index_project(str(project_dir), "FourTIndex")
    
    # get_project_roadmap
    roadmap_json = mcp_server.get_project_roadmap("FourTIndex")
    roadmap = json.loads(roadmap_json)
    
    assert "Python" in roadmap["framework_signatures"]
    assert "Django" in roadmap["framework_signatures"]
    assert "FastAPI" in roadmap["framework_signatures"]
    assert "pytest" in roadmap["framework_signatures"]


def test_health_dashboard_and_errors():
    dashboard = mcp_server.get_health_dashboard()
    assert "FOURTINDEX HEALTH DASHBOARD" in dashboard
    assert "Status:             Healthy" in dashboard
    
    # Trigger an error in save_session_summary to log it
    mcp_server.save_session_summary(None, None) # will throw TypeError or similar
    
    dashboard_with_errors = mcp_server.get_health_dashboard(output_json=True)
    data = json.loads(dashboard_with_errors)
    assert len(data["recent_errors"]) > 0
    assert "save_session_summary" in data["recent_errors"][0]["message"]
