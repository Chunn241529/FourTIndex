import argparse
import time
import os
import sys
from pathlib import Path

# Ensure PYTHONPATH includes root directory
sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from src import mcp_server
from src.config import Config
from src.database import Database
from src.embedder import Embedder
from src.indexer import Indexer
from src.indexing_service import IndexingService

def get_token_count(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return max(1, len(text) // 4)

def estimate_cost(tokens: int, cost_per_1m: float = 3.0) -> float:
    return (tokens / 1_000_000) * cost_per_1m

def main():
    parser = argparse.ArgumentParser(description="Compare metrics between No-FourTIndex (Full Dump) and With-FourTIndex (Targeted Search).")
    parser.add_argument("--path", type=str, default=".", help="Path to repository")
    parser.add_argument("--project-name", type=str, default="bench-real-index", help="Project name in DB")
    parser.add_argument("--query", type=str, default="embedding index search", help="Search query to use")
    parser.add_argument("--cost-per-1m", type=float, default=3.0, help="LLM cost per 1M input tokens")
    args = parser.parse_args()

    project_dir = Path(args.path).absolute()
    
    # 1. Without FourTIndex (Full text dump of supported files)
    print("Evaluating [Without FourTIndex] (Full Codebase Dump)...")
    config = Config()
    
    t0_without = time.perf_counter()
    full_text = []
    files_scanned = 0
    lines_scanned = 0
    
    for root, _, files in os.walk(project_dir):
        # Exclude common git/venv folders
        if any(ignored in Path(root).parts for ignored in ['.git', '.venv', '__pycache__', 'node_modules']):
            continue
            
        for f in files:
            if f.endswith(tuple(config.supported_extensions)):
                file_path = Path(root) / f
                try:
                    text = file_path.read_text(encoding="utf-8")
                    full_text.append(f"--- {file_path.name} ---\n{text}")
                    files_scanned += 1
                    lines_scanned += text.count("\n") + 1
                except UnicodeDecodeError:
                    pass

    full_context_str = "\n".join(full_text)
    t_without_ms = (time.perf_counter() - t0_without) * 1000
    without_tokens = get_token_count(full_context_str)
    without_cost = estimate_cost(without_tokens, args.cost_per_1m)

    # 2. With FourTIndex (Vector Search)
    print("\nEvaluating [With FourTIndex] (Targeted Vector Search)...")
    db = Database(config)
    
    saved_path = db.get_project_path(args.project_name)
    if not saved_path:
        print(f"\nError: Project '{args.project_name}' not found in DB.")
        print(f"Please run indexing first: python main.py index {args.path} --project-name {args.project_name}")
        sys.exit(1)
        
    mcp_server.config = config
    mcp_server.db = db
    mcp_server.embedder = Embedder(config)
    mcp_server.indexer = Indexer(config)
    mcp_server.indexing_service = IndexingService(config)

    t0_with = time.perf_counter()
    # Execute actual search codebase (runs sequentially on queries)
    try:
        search_result_str = mcp_server.search_codebase(args.query, args.project_name, output_json=False)
    except Exception as e:
        print(f"Search failed: {e}")
        sys.exit(1)
        
    t_with_ms = (time.perf_counter() - t0_with) * 1000
    with_tokens = get_token_count(search_result_str)
    with_cost = estimate_cost(with_tokens, args.cost_per_1m)

    # 3. Print Results
    print("\n" + "="*60)
    print("COMPARISON RESULTS: NO FOURTINDEX vs. FOURTINDEX")
    print("="*60)
    print(f"Target: {project_dir.name} ({files_scanned} files, {lines_scanned:,} lines)")
    print(f"Query:  '{args.query}'\n")

    print(f"--- Without FourTIndex (Full Dump) ---")
    print(f"Latency: {t_without_ms:.2f} ms")
    print(f"Tokens:  {without_tokens:,} tokens")
    print(f"Cost:    ${without_cost:.4f} USD\n")

    print(f"--- With FourTIndex (Vector Search) ---")
    print(f"Latency: {t_with_ms:.2f} ms")
    print(f"Tokens:  {with_tokens:,} tokens")
    print(f"Cost:    ${with_cost:.4f} USD\n")

    print(f"--- Improvements ---")
    if with_tokens > 0:
        print(f"Context Reduction: {without_tokens / with_tokens:.1f}x smaller context")
    if with_cost > 0:
        cost_savings = ((without_cost - with_cost) / without_cost) * 100
        print(f"Cost Savings:      {cost_savings:.1f}% cheaper per request")
    print("="*60)

if __name__ == "__main__":
    main()
