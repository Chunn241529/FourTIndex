import ast
from pathlib import Path


MCP_SERVER_PATH = Path(__file__).parents[1] / "src" / "mcp_server.py"


def test_mcp_index_project_defaults_to_local_embeddings():
    module = ast.parse(MCP_SERVER_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "index_project"
    )
    defaults = dict(
        zip(
            (argument.arg for argument in function.args.args[-len(function.args.defaults) :]),
            function.args.defaults,
        )
    )

    assert ast.literal_eval(defaults["embedding_provider"]) == "auto"
    assert "remains on the local machine" in ast.get_docstring(function)


def test_mcp_new_tools_exist():
    module = ast.parse(MCP_SERVER_PATH.read_text(encoding="utf-8"))
    functions = [
        node.name
        for node in module.body
        if isinstance(node, ast.FunctionDef)
    ]
    assert "get_project_roadmap" in functions
    assert "list_projects" in functions
    assert "get_token_report" in functions
    
    # Check that search_codebase has the language parameter
    search_fn = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "search_codebase"
    )
    args = [arg.arg for arg in search_fn.args.args]
    assert "language" in args

