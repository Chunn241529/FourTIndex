import argparse
import subprocess
import time
from pathlib import Path
import sys

def detect_provider() -> str:
    import urllib.request
    import urllib.error
    
    lmstudio_url = "http://127.0.0.1:2401/v1/models"
    ollama_url = "http://localhost:11434/api/tags"
    
    try:
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

def main():
    parser = argparse.ArgumentParser(description="Benchmark end-to-end indexing on a real codebase.")
    parser.add_argument("--path", type=str, default=".", help="Path to the repository to index (default: current directory)")
    parser.add_argument("--project-name", type=str, default="bench-real-index", help="Project name to store in DB")
    parser.add_argument("--workers", type=int, default=1, help="Number of file parsing workers")
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding batch size")
    args = parser.parse_args()

    target_dir = Path(args.path).absolute()
    if not target_dir.is_dir():
        print(f"Error: Path '{args.path}' is not a valid directory.")
        sys.exit(1)

    provider = detect_provider()
    print(f"Target Directory: {target_dir}")
    print(f"Embedding Provider: {provider.upper()}")
    
    print(f"\nRunning BATCHED indexing (workers={args.workers}, batch-size={args.batch_size})...")
    start = time.perf_counter()
    
    cmd = [
        "python", "main.py", "index", str(target_dir),
        "--project-name", args.project_name,
        "--rebuild",
        "--embedding-provider", provider,
        "--workers", str(args.workers),
        "--batch-size", str(args.batch_size)
    ]
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Indexing failed with exit code {e.returncode}")
        sys.exit(1)
        
    t_index = time.perf_counter() - start

    print("\n" + "="*50)
    print(f"Benchmark Results:")
    print(f"  - Repository: {target_dir.name}")
    print(f"  - Total Indexing Time: {t_index:.2f}s")
    print("="*50)

    # Verify registry roadmap
    try:
        from src.database import Database
        from src.config import Config
        db = Database(Config())
        roadmap = db.get_project_roadmap(args.project_name)
        if roadmap:
            print("\n" + "="*50)
            print("Omni-Language Benchmark Registry Verification:")
            print(f"  - Detected Frameworks: {roadmap['framework_signatures']}")
            print(f"  - Total Files in Directory Tree: {len(roadmap['directory_tree']['children'])}")
            print("="*50)
    except Exception as e:
        print(f"Warning: Failed to retrieve benchmark registry roadmap: {e}")

if __name__ == "__main__":
    main()
