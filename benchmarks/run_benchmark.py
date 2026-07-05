import subprocess
import time
import shutil
import os
from pathlib import Path

def create_fixture(root: Path, file_count: int, lines_per_file: int) -> None:
    body = "\n".join(f"    value_{line} = {line}" for line in range(lines_per_file))
    for index in range(file_count):
        (root / f"module_{index:05d}.py").write_text(
            f"def function_{index}():\n{body}\n    return value_0\n", encoding="utf-8"
        )

def main():
    fixture_dir = Path("benchmarks/temp_benchmark_project")
    if fixture_dir.exists():
        shutil.rmtree(fixture_dir)
    fixture_dir.mkdir(parents=True)

    print("Generating 50 files for benchmark...")
    create_fixture(fixture_dir, 50, 100)

    try:
        # Run Sequential indexing (1 worker, batch size 1)
        print("\n[1/2] Running SEQUENTIAL indexing (workers=1, batch-size=1)...")
        start = time.perf_counter()
        subprocess.run([
            "python", "main.py", "index", str(fixture_dir),
            "--project-name", "bench-seq",
            "--rebuild",
            "--embedding-provider", "ollama",
            "--workers", "1",
            "--batch-size", "1"
        ], check=True)
        t_seq = time.perf_counter() - start
        print(f"-> Sequential finished in {t_seq:.2f}s")

        # Run Parallel & Batched indexing (workers=4, batch-size=32)
        print("\n[2/2] Running PARALLEL & BATCHED indexing (workers=4, batch-size=32)...")
        start = time.perf_counter()
        subprocess.run([
            "python", "main.py", "index", str(fixture_dir),
            "--project-name", "bench-par",
            "--rebuild",
            "--embedding-provider", "ollama",
            "--workers", "4",
            "--batch-size", "32"
        ], check=True)
        t_par = time.perf_counter() - start
        print(f"-> Parallel & Batched finished in {t_par:.2f}s")

        speedup = t_seq / t_par
        print("\n" + "="*50)
        print(f"Benchmark Results:")
        print(f"  - Sequential: {t_seq:.2f}s")
        print(f"  - Parallel & Batched: {t_par:.2f}s")
        print(f"  - Speedup Ratio: {speedup:.2f}x")
        print("="*50)
        
        if speedup >= 3.0:
            print("SUCCESS: Performance target achieved (>3x speedup)!")
        else:
            print("WARNING: Speedup is less than 3x. Check system load or Ollama settings.")

    finally:
        # Clean up
        print("\nCleaning up fixture directory...")
        shutil.rmtree(fixture_dir, ignore_errors=True)

if __name__ == "__main__":
    main()
