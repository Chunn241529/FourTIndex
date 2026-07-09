import argparse
import time
import json
import statistics
import os
import random
from pathlib import Path

# Ensure PYTHONPATH includes root directory
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from src import mcp_server
from src.config import Config
from src.database import Database
from src.embedder import Embedder
from src.indexer import Indexer
from src.indexing_service import IndexingService

def run_benchmark(project_name: str, project_path: str):
    config = Config()
    db = Database(config)
    embedder = Embedder(config)
    indexer = Indexer(config)
    indexing_service = IndexingService(config)

    mcp_server.config = config
    mcp_server.db = db
    mcp_server.embedder = embedder
    mcp_server.indexer = indexer
    mcp_server.indexing_service = indexing_service

    saved_path = db.get_project_path(project_name)
    if not saved_path:
        print(f"Error: Project '{project_name}' is not indexed.")
        print(f"Run: python main.py index {project_path} --project-name {project_name}")
        sys.exit(1)

    print(f"Project '{project_name}' is loaded from {saved_path}")

    # Find a random file to test get_file_outline
    test_file = ""
    for root, _, files in os.walk(saved_path):
        for f in files:
            if f.endswith(tuple(config.supported_extensions)):
                test_file = os.path.relpath(os.path.join(root, f), saved_path)
                break
        if test_file:
            break
            
    if not test_file:
        print("Warning: No supported source files found in the project. Using a dummy filename.")
        test_file = "dummy.py"

    print(f"Using test file for outline: {test_file}")

    # Ensure there is at least one session summary to search
    try:
        mcp_server.save_session_summary("benchmark_summary", "This is a benchmark summary test.", project_name)
    except Exception:
        pass

    iterations = 20
    latencies = {
        "diff_index_status": [],
        "search_codebase": [],
        "get_file_outline": [],
        "search_session_summaries": [],
        "get_health_dashboard": []
    }
    
    print(f"Running {iterations} iterations for each MCP tool...")
    
    for _ in range(iterations):
        # 1. diff_index_status
        t0 = time.perf_counter()
        mcp_server.diff_index_status(project_name, output_json=True)
        latencies["diff_index_status"].append(time.perf_counter() - t0)
        
        # 2. search_codebase (Requires real embedding call, so it's slower)
        t0 = time.perf_counter()
        mcp_server.search_codebase("index", project_name, output_json=True)
        latencies["search_codebase"].append(time.perf_counter() - t0)
        
        # 3. get_file_outline
        t0 = time.perf_counter()
        mcp_server.get_file_outline(test_file, project_name, output_json=True)
        latencies["get_file_outline"].append(time.perf_counter() - t0)
        
        # 4. search_session_summaries
        t0 = time.perf_counter()
        mcp_server.search_session_summaries("benchmark", project_name, output_json=True)
        latencies["search_session_summaries"].append(time.perf_counter() - t0)
        
        # 5. get_health_dashboard
        t0 = time.perf_counter()
        mcp_server.get_health_dashboard(output_json=True)
        latencies["get_health_dashboard"].append(time.perf_counter() - t0)
        
    print("\n=== Real MCP Tool Latency Results ===")
    results = {}
    for name, times in latencies.items():
        avg_ms = statistics.mean(times) * 1000
        p95_ms = statistics.quantiles(times, n=20)[18] * 1000 if len(times) > 1 else avg_ms
        ops_sec = 1.0 / max(0.0001, statistics.mean(times))
        results[name] = {"avg_ms": avg_ms, "p95_ms": p95_ms, "ops_sec": ops_sec}
        print(f"  - {name:25s} | Avg: {avg_ms:7.2f} ms | p95: {p95_ms:7.2f} ms | Throughput: {ops_sec:8.1f} ops/sec")
        
    Path("benchmarks").mkdir(exist_ok=True)
    with open("benchmarks/benchmark_mcp_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark MCP tools on a real codebase.")
    parser.add_argument("--path", type=str, default=".", help="Path to the repository to index (default: current directory)")
    parser.add_argument("--project-name", type=str, default="bench-real-index", help="Project name to store in DB")
    args = parser.parse_args()
    
    run_benchmark(args.project_name, str(Path(args.path).absolute()))
