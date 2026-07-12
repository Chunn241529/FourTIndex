import os
from src.indexer import EXTENSION_TO_LANGUAGE
from src.tree_sitter_compat import get_tree_sitter_parser


def check_single_file(path: str) -> list[dict]:
    ext = os.path.splitext(path)[1].lower()
    lang_name = EXTENSION_TO_LANGUAGE.get(ext)
    if not lang_name:
        return []  # Ignore unsupported file types silently when checking directory
        
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return [{"type": "File Read Error", "line": 0, "col": 0, "line_text": str(e), "pointer": ""}]
        
    try:
        parser = get_tree_sitter_parser(lang_name)
        if not parser:
            return [{"type": "Parser Load Error", "line": 0, "col": 0, "line_text": f"Failed to load tree-sitter parser for {lang_name}", "pointer": ""}]
            
        tree = parser.parse(bytes(content, "utf-8"))
        
        def _traverse_for_errors(node) -> list[dict]:
            errors = []
            is_err = node.type == "ERROR"
            is_missing = node.is_missing
            if is_err or is_missing:
                start_line, start_col = node.start_point
                lines = content.splitlines()
                line_text = ""
                if start_line < len(lines):
                    line_text = lines[start_line]
                    
                pointer = ""
                if line_text:
                    col_aligned = min(start_col, len(line_text))
                    pointer = " " * col_aligned + "^"
                    
                error_type = "Syntax Error" if is_err else f"Missing Token ({node.type})"
                errors.append({
                    "type": error_type,
                    "line": start_line + 1,
                    "col": start_col,
                    "line_text": line_text,
                    "pointer": pointer
                })
                if is_err:
                    return errors
                    
            for child in node.children:
                errors.extend(_traverse_for_errors(child))
            return errors
            
        return _traverse_for_errors(tree.root_node)
    except Exception as e:
        return [{"type": "Parser Execution Error", "line": 0, "col": 0, "line_text": str(e), "pointer": ""}]
