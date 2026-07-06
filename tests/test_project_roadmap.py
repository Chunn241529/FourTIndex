import os
import json
import sqlite3
import pytest
from src.config import Config
from src.database import Database

def test_build_project_roadmap(tmp_path):
    # Set up config with tmp db path
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join([
            "project:",
            "  name: test-project",
            "  exclude_dirs: [.git, node_modules]",
            "database:",
            f"  persist_directory: '{(tmp_path / 'db').as_posix()}'"
        ]),
        encoding="utf-8"
    )
    config = Config(str(config_path))
    
    # Create test directory structure
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    (project_dir / "src").mkdir()
    (project_dir / "src" / "index.js").write_text("console.log('hello');", encoding="utf-8")
    
    # Signatures
    (project_dir / "project.godot").write_text("", encoding="utf-8")
    (project_dir / "default.project.json").write_text("{}", encoding="utf-8") # Roblox signature
    
    db = Database(config)
    
    tree, signatures = db.build_project_roadmap(str(project_dir))
    
    assert "Godot Engine" in signatures
    assert "Roblox (Lua)" in signatures
    assert tree["name"] == "my_project"
    
    # Check children structure
    child_names = {c["name"] for c in tree["children"]}
    assert "src" in child_names
    assert "project.godot" in child_names
    
    # Test DB storage
    db.save_project_roadmap("my_project", tree, signatures)
    
    roadmap = db.get_project_roadmap("my_project")
    assert roadmap is not None
    assert roadmap["project_name"] == "my_project"
    assert "Godot Engine" in roadmap["framework_signatures"]
    
    projects = db.list_projects()
    project_names = {p["project_name"] for p in projects}
    assert "my_project" in project_names
