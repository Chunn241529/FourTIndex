import os
import pytest
from src.mcp_server import check_syntax

def test_check_syntax_python_ok(tmp_path):
    py_file = tmp_path / "valid.py"
    py_file.write_text("def hello():\n    print('Hello')\n", encoding="utf-8")
    
    res = check_syntax(str(py_file), project_name="FourTIndex")
    assert "No syntax errors found" in res
    assert "✓" in res

def test_check_syntax_python_error(tmp_path):
    py_file = tmp_path / "invalid.py"
    py_file.write_text("def hello(\n    print('Hello')\n", encoding="utf-8")
    
    res = check_syntax(str(py_file), project_name="FourTIndex")
    assert "Found" in res
    assert "syntax error" in res.lower()

def test_check_syntax_unsupported_ext(tmp_path):
    txt_file = tmp_path / "doc.txt"
    txt_file.write_text("Hello world", encoding="utf-8")
    
    res = check_syntax(str(txt_file), project_name="FourTIndex")
    assert "Unsupported file type" in res
