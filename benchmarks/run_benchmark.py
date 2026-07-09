import subprocess
import time
import shutil
import os
from pathlib import Path

def create_fixture(root: Path, file_count: int, lines_per_file: int) -> None:
    # Framework signatures
    (root / "project.godot").write_text("", encoding="utf-8")
    (root / "default.project.json").write_text("{}", encoding="utf-8")
    
    body = "\n".join(f"    value_{line} = {line}" for line in range(lines_per_file))
    for index in range(file_count):
        ext_idx = index % 6
        if ext_idx == 0:
            (root / f"module_{index:05d}.py").write_text(
                f"class PythonClass_{index}:\n"
                f"    def method_{index}(self):\n"
                f"        return {index}\n", encoding="utf-8"
            )
        elif ext_idx == 1:
            (root / f"module_{index:05d}.cs").write_text(
                f"namespace Game {{\n"
                f"    public class CSharpClass_{index} {{\n"
                f"        public void CSharpMethod_{index}() {{\n"
                f"            int val = {index};\n"
                f"        }}\n"
                f"    }}\n"
                f"}}", encoding="utf-8"
            )
        elif ext_idx == 2:
            (root / f"module_{index:05d}.ts").write_text(
                f"class TSClass_{index} {{\n"
                f"    tsMethod_{index}(x: number): void {{\n"
                f"        console.log(x + {index});\n"
                f"    }}\n"
                f"}}", encoding="utf-8"
            )
        elif ext_idx == 3:
            (root / f"module_{index:05d}.lua").write_text(
                f"function lua_func_{index}()\n"
                f"    return {index}\n"
                f"end", encoding="utf-8"
            )
        elif ext_idx == 4:
            (root / f"module_{index:05d}.cpp").write_text(
                f"class CppClass_{index} {{\n"
                f"public:\n"
                f"    void cppMethod_{index}() {{\n"
                f"        int a = {index};\n"
                f"    }}\n"
                f"}};", encoding="utf-8"
            )
        elif ext_idx == 5:
            # Swift triggers graceful sliding-window fallback
            (root / f"module_{index:05d}.swift").write_text(
                f"func swiftFunc_{index}() -> Int {{\n"
                f"    return {index}\n"
                f"}}", encoding="utf-8"
            )

def main():
    fixture_dir = Path("benchmarks/temp_benchmark_project")
    if fixture_dir.exists():
        shutil.rmtree(fixture_dir)
    fixture_dir.mkdir(parents=True)

    print("Generating 50 files for benchmark...")
    create_fixture(fixture_dir, 50, 100)

    # Detect provider with fallbacks: LM Studio -> Ollama -> Fake
    def detect_provider() -> str:
        import urllib.request
        import urllib.error
        
        lmstudio_url = "http://127.0.0.1:2401/v1/models"
        ollama_url = "http://localhost:11434/api/tags"
        
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))
            from src.config import Config
            config = Config()
            lmstudio_url = f"{config.lmstudio_host.rstrip('/')}/v1/models"
            ollama_url = f"{config.ollama_host.rstrip('/')}/api/tags"
        except Exception:
            pass

        def check_url(url: str) -> bool:
            try:
                req = urllib.request.Request(url, method="GET")
                req.add_header("User-Agent", "Mozilla/5.0")
                with urllib.request.urlopen(req, timeout=1.0) as res:
                    return res.status in (200, 401)
            except urllib.error.HTTPError as e:
                return e.code in (200, 401)
            except Exception:
                return False

        if check_url(lmstudio_url):
            return "lmstudio"
        elif check_url(ollama_url):
            return "ollama"
        return "fake"

    provider = detect_provider()
    print(f"Using embedding provider: {provider.upper()}")

    try:
        # Run Sequential indexing (1 worker, batch size 1)
        print("\n[1/2] Running SEQUENTIAL indexing (workers=1, batch-size=1)...")
        start = time.perf_counter()
        subprocess.run([
            "python", "main.py", "index", str(fixture_dir),
            "--project-name", "bench-seq",
            "--rebuild",
            "--embedding-provider", provider,
            "--workers", "1",
            "--batch-size", "1"
        ], check=True)
        t_seq = time.perf_counter() - start
        print(f"-> Sequential finished in {t_seq:.2f}s")

        # Run Batched indexing sequentially (workers=1, batch-size=32) to prevent dump
        print("\n[2/2] Running BATCHED indexing sequentially (workers=1, batch-size=32)...")
        start = time.perf_counter()
        subprocess.run([
            "python", "main.py", "index", str(fixture_dir),
            "--project-name", "bench-par",
            "--rebuild",
            "--embedding-provider", provider,
            "--workers", "1",
            "--batch-size", "32"
        ], check=True)
        t_par = time.perf_counter() - start
        print(f"-> Batched sequentially finished in {t_par:.2f}s")

        speedup = t_seq / t_par
        print("\n" + "="*50)
        print(f"Benchmark Results:")
        print(f"  - Sequential: {t_seq:.2f}s")
        print(f"  - Batched Sequentially: {t_par:.2f}s")
        print(f"  - Speedup Ratio: {speedup:.2f}x")
        print("="*50)

        # Verify registry roadmap
        try:
            from src.database import Database
            from src.config import Config
            db = Database(Config())
            roadmap = db.get_project_roadmap("bench-par")
            if roadmap:
                print("\n" + "="*50)
                print("Omni-Language Benchmark Registry Verification:")
                print(f"  - Detected Frameworks: {roadmap['framework_signatures']}")
                print(f"  - Total Files in Directory Tree: {len(roadmap['directory_tree']['children'])}")
                print("="*50)
        except Exception as e:
            print(f"Warning: Failed to retrieve benchmark registry roadmap: {e}")
        
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
