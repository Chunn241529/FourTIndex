import os
import time
from pathlib import Path

# Ensure PYTHONPATH includes root directory
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from src.config import Config
from src.embedder import Embedder

def main():
    config = Config()
    embedder = Embedder(config)
    
    print(f"Active Provider: {embedder.provider.upper()}")
    print(f"Active Model:    {embedder.model}")
    print("Testing connection...")
    
    try:
        t0 = time.perf_counter()
        vec = embedder.get_embedding("Test connection latency")
        lat = (time.perf_counter() - t0) * 1000
        print(f"✓ Success! Connection is online.")
        print(f"  - Embedding Dimension: {len(vec)}")
        print(f"  - 1-item Latency:      {lat:.2f} ms")
    except Exception as e:
        print(f"✗ Connection Failed: {e}")
        print("\nNote: Please ensure LM Studio or Ollama is running and configured correctly in config.yaml.")
        return

    # Benchmark run
    iterations = 20
    latencies = []
    print(f"\nRunning {iterations} iterations of real API calls...")
    for i in range(iterations):
        t0 = time.perf_counter()
        embedder.get_embedding(f"Query iteration number {i}")
        latencies.append(time.perf_counter() - t0)
        
    avg_ms = (sum(latencies) / len(latencies)) * 1000
    ops_sec = 1.0 / (sum(latencies) / len(latencies))
    print("\n=== Real Embedding API Latency Results ===")
    print(f"  - Average Latency: {avg_ms:.2f} ms")
    print(f"  - Throughput:      {ops_sec:.1f} queries/sec")

if __name__ == "__main__":
    main()
