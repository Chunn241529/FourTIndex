import os
import time
import json
import statistics
from pathlib import Path

# Ensure PYTHONPATH includes root directory
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from src import mcp_server
from src.config import Config
from src.database import Database
from src.embedder import Embedder
from src.indexer import Indexer
from tests.test_indexing_service import FakeProvider

def setup_benchmark_environment(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join([
            "project:",
            "  name: BenchProject",
            "  exclude_dirs: [.git]",
            "  supported_extensions: [.py]",
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
    
    # Mock class-level EmbeddingManager to return FakeProvider
    from src.embedding.manager import EmbeddingManager
    EmbeddingManager.select_for_new_index = lambda self, requested="auto": setattr(self, "provider", fake_provider) or fake_provider
    EmbeddingManager.load_profile = lambda self, profile: setattr(self, "provider", fake_provider) or fake_provider
    
    # Also mock instance-level or global embedder calls
    test_embedder.provider = "fake"
    test_embedder.model = "fake-model"
    test_embedder.get_embedding = lambda text: fake_provider.embed_query(text)
    test_embedder.get_embeddings_batch = lambda texts: fake_provider.embed_documents(texts)
    
    # Ensure FakeProvider returns static unit vectors to avoid neg cosine similarity
    FakeProvider._vector = lambda *args: [1.0, 0.0, 0.0]
    
    test_indexer = Indexer(test_config)
    
    mcp_server.config = test_config
    mcp_server.db = test_db
    mcp_server.embedder = test_embedder
    mcp_server.indexer = test_indexer
    
    # Save a mock project path
    project_dir = tmp_path / "test-project"
    project_dir.mkdir(exist_ok=True)
    mcp_server.db.save_project_path("BenchProject", str(project_dir))
    
    return project_dir, test_config

def run_benchmark():
    import tempfile
    import shutil
    
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        project_dir, test_config = setup_benchmark_environment(tmp_dir)
        
        # Write 10 mock python files
        for i in range(10):
            (project_dir / f"file_{i}.py").write_text(
                f"class Class_{i}:\n    def method_{i}(self):\n        return {i}\n",
                encoding="utf-8"
            )
            
        print("Indexing benchmark project...")
        mcp_server.index_project(str(project_dir), "BenchProject")
        
        # Save a session summary to search against
        mcp_server.save_session_summary("sess_bench", "Design decisions benchmark", "BenchProject")
        
        iterations = 50
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
            mcp_server.diff_index_status("BenchProject", output_json=True)
            latencies["diff_index_status"].append(time.perf_counter() - t0)
            
            # 2. search_codebase
            t0 = time.perf_counter()
            mcp_server.search_codebase("method", "BenchProject", output_json=True)
            latencies["search_codebase"].append(time.perf_counter() - t0)
            
            # 3. get_file_outline
            t0 = time.perf_counter()
            mcp_server.get_file_outline("file_0.py", "BenchProject", output_json=True)
            latencies["get_file_outline"].append(time.perf_counter() - t0)
            
            # 4. search_session_summaries
            t0 = time.perf_counter()
            mcp_server.search_session_summaries("Design", "BenchProject", output_json=True)
            latencies["search_session_summaries"].append(time.perf_counter() - t0)
            
            # 5. get_health_dashboard
            t0 = time.perf_counter()
            mcp_server.get_health_dashboard(output_json=True)
            latencies["get_health_dashboard"].append(time.perf_counter() - t0)
            
        print("\n=== Benchmark Results ===")
        results = {}
        for name, times in latencies.items():
            avg_ms = statistics.mean(times) * 1000
            # Use quantiles for p95
            p95_ms = statistics.quantiles(times, n=20)[18] * 1000
            ops_sec = 1.0 / statistics.mean(times)
            results[name] = {"avg_ms": avg_ms, "p95_ms": p95_ms, "ops_sec": ops_sec}
            print(f"  - {name:25s} | Avg: {avg_ms:6.2f} ms | p95: {p95_ms:6.2f} ms | Throughput: {ops_sec:8.1f} ops/sec")
            
        # Write results to benchmarks/benchmark_results.json
        Path("benchmarks").mkdir(exist_ok=True)
        with open("benchmarks/benchmark_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
            
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

if __name__ == "__main__":
    run_benchmark()
