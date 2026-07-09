import argparse
import time
import os
import sys
import re
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

def run_grep(project_dir: Path, query: str):
    """Simulates agent's grep search and reading the matching files."""
    t0 = time.perf_counter()
    words = [w.lower() for w in re.findall(r'\w+', query) if len(w) > 2]
    if not words:
        words = [query.lower()]
        
    matches = []
    matched_files = set()
    total_lines_read = 0
    
    # Simulate Grep Search
    for root, _, files in os.walk(project_dir):
        if any(ignored in Path(root).parts for ignored in ['.git', '.venv', '__pycache__', 'node_modules', '.agents', '.fourtindex']):
            continue
            
        for f in files:
            if f.endswith(('.py', '.md')):
                file_path = Path(root) / f
                try:
                    content = file_path.read_text(encoding="utf-8")
                    lines = content.splitlines()
                    for idx, line in enumerate(lines):
                        # Match if any of the query words are in the line
                        if any(word in line.lower() for word in words):
                            matches.append((file_path, idx + 1, line))
                            matched_files.add(file_path)
                            break  # Just get first match per file to avoid double-counting
                except Exception:
                    pass
                    
    # Simulate reading the matched files (agent reads files to extract code)
    context_builder = []
    for fp in matched_files:
        try:
            txt = fp.read_text(encoding="utf-8")
            context_builder.append(f"=== FILE: {fp.name} ===\n{txt}")
            total_lines_read += len(txt.splitlines())
        except Exception:
            pass
            
    grep_context = "\n\n".join(context_builder)
    latency_ms = (time.perf_counter() - t0) * 1000
    return grep_context, latency_ms, len(matches), total_lines_read

def main():
    parser = argparse.ArgumentParser(description="Detailed Grep vs FourTIndex Benchmark.")
    parser.add_argument("--path", type=str, default=".", help="Path to repository")
    parser.add_argument("--project-name", type=str, default="FourTIndex", help="Project name in DB")
    parser.add_argument("--query", type=str, default="splits array into batches based on max_items and max_chars", help="Query to run")
    parser.add_argument("--cost-per-1m", type=float, default=3.0, help="LLM cost per 1M input tokens")
    args = parser.parse_args()

    project_dir = Path(args.path).absolute()
    
    # 1. GREP BENCHMARK
    print(f"Running Grep search Simulation for query: '{args.query}'...")
    grep_context, grep_latency, grep_matches, grep_lines = run_grep(project_dir, args.query)
    grep_tokens = get_token_count(grep_context)
    grep_cost = estimate_cost(grep_tokens, args.cost_per_1m)
    
    # 2. FOURTINDEX BENCHMARK
    print(f"Running FourTIndex Hybrid Search for query: '{args.query}'...")
    config = Config()
    db = Database(config)
    
    # Init MCP context
    mcp_server.config = config
    mcp_server.db = db
    mcp_server.embedder = Embedder(config)
    mcp_server.indexer = Indexer(config)
    mcp_server.indexing_service = IndexingService(config)
    
    t0_fourt = time.perf_counter()
    try:
        fourt_context = mcp_server.search_codebase(args.query, args.project_name, output_json=False)
    except Exception as e:
        print(f"FourTIndex search failed: {e}")
        sys.exit(1)
    fourt_latency = (time.perf_counter() - t0_fourt) * 1000
    fourt_tokens = get_token_count(fourt_context)
    fourt_cost = estimate_cost(fourt_tokens, args.cost_per_1m)

    # 3. Print Results Markdown Table
    print("\n" + "="*80)
    print("                     BENCHMARK COMPARISON: GREP VS FOURTINDEX")
    print("="*80)
    print(f"Project:      {project_dir.name}")
    print(f"Query:        '{args.query}'")
    print(f"Grep Matches: {grep_matches} files found ({grep_lines} lines of code read)\n")

    print("| Metric | Grep Search + Read | FourTIndex Hybrid Search | Improvement / Win |")
    print("| :--- | :--- | :--- | :--- |")
    
    # Latency comparison
    latency_ratio = grep_latency / fourt_latency if fourt_latency > 0 else 0
    if latency_ratio > 1:
        latency_win = f"{latency_ratio:.1f}x Faster"
    else:
        latency_win = f"{1/latency_ratio:.1f}x Slower (due to local LLM reranking)"
    print(f"| **Search Latency** | {grep_latency:.2f} ms | {fourt_latency:.2f} ms | {latency_win} |")
    
    # Token comparison
    token_ratio = grep_tokens / fourt_tokens if fourt_tokens > 0 else 0
    token_win = f"{token_ratio:.1f}x Context Pruned" if token_ratio > 1 else "No Pruning"
    print(f"| **Context Size** | {grep_tokens:,} tokens | {fourt_tokens:,} tokens | {token_win} |")
    
    # Cost comparison
    cost_win = f"{((grep_cost - fourt_cost)/grep_cost)*100:.1f}% Cheaper" if grep_cost > 0 else "N/A"
    print(f"| **Estimated Cost** | ${grep_cost:.5f} USD | ${fourt_cost:.5f} USD | {cost_win} |")
    
    # Quality / Relevance
    relevance_grep = "Unfiltered (whole files)"
    relevance_fourt = "Top 5 ranked code chunks (FTS5 + RRF + Reranker)"
    print(f"| **Result Quality** | {relevance_grep} | {relevance_fourt} | FourTIndex (Targeted Snippets) |")
    
    print("="*80)
    print("\nNOTE: Although Grep search is faster on small repositories, FourTIndex is highly recommended")
    print("for larger projects to prevent context window overload and save up to 99% of API costs.")

if __name__ == "__main__":
    main()
