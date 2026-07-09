import os
import re
from pathlib import Path
import time
import logging

logger = logging.getLogger("FourTIndexKeywordSearch")

def build_symbol_regex(keyword: str) -> re.Pattern:
    """Build a regex to find definitions of the keyword."""
    # Look for common definition patterns: def, class, function, const, let, var, interface, type
    # e.g., 'def keyword', 'class keyword', 'function keyword', 'const keyword ='
    pattern = rf"^(?:\s*)(?:def|class|function|const|let|var|interface|type)\s+{re.escape(keyword)}\b"
    return re.compile(pattern)

def is_valid_keyword(query: str) -> bool:
    """Check if the query is a single word suitable for exact keyword search."""
    query = query.strip()
    if not query:
        return False
    # Must be a single word, allowing underscores and alphanumeric chars
    return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", query))

def search_exact_keyword(project_dir: str, keyword: str, extensions: list[str]) -> list[dict]:
    """
    Search the project for exact definitions of the keyword.
    Returns a list of dicts with file, line, and content.
    """
    results = []
    regex = build_symbol_regex(keyword)
    project_path = Path(project_dir).resolve()
    
    ignore_dirs = {'.git', '.venv', '__pycache__', 'node_modules', 'dist', 'build', '.fourtindex', '.pytest_cache'}
    
    t0 = time.perf_counter()
    files_scanned = 0
    
    for root, dirs, files in os.walk(project_path):
        # Filter directories
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        
        for file in files:
            ext = Path(file).suffix.lower()
            if ext in extensions:
                file_path = Path(root) / file
                try:
                    content = file_path.read_text(encoding="utf-8")
                    files_scanned += 1
                    
                    # Check if the exact keyword is even in the file first before regex
                    if keyword not in content:
                        continue
                        
                    lines = content.splitlines()
                    for i, line in enumerate(lines):
                        if regex.search(line):
                            # Grab context lines
                            start = max(0, i - 2)
                            end = min(len(lines), i + 10)
                            context = "\n".join(lines[start:end])
                            
                            results.append({
                                "file": str(file_path.relative_to(project_path).as_posix()),
                                "line": i + 1,
                                "content": context
                            })
                            # We found a definition in this file, we can break or continue for more
                            break
                except UnicodeDecodeError:
                    pass
                except Exception as e:
                    logger.debug(f"Error reading {file_path}: {e}")

    t_ms = (time.perf_counter() - t0) * 1000
    logger.info(f"Keyword search for '{keyword}' scanned {files_scanned} files in {t_ms:.2f}ms. Found {len(results)} matches.")
    
    return results

def format_keyword_results(query: str, results: list[dict]) -> str:
    """Format exact match results into markdown."""
    if not results:
        return f"No exact symbol definitions found for '{query}'."
        
    output = [f"=== EXACT MATCH (Keyword Search) for '{query}' ==="]
    for res in results:
        output.append(f"\n# File: {res['file']} | Line: {res['line']}")
        output.append("-" * 40)
        output.append(res['content'])
        
    return "\n".join(output)
