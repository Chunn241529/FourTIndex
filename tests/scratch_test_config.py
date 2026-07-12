import sys
import os

# Ensure we can import from src
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from src.config import Config

def main():
    config = Config()
    print(f"Loaded config from: {config.config_path}")
    print("--- Hardware Detection ---")
    print(f"VRAM detected: {config._detect_vram_mb()} MB")
    print(f"RAM detected: {config._get_system_ram_gb()} GB")
    print(f"CPU threads detected: {os.cpu_count()}")
    
    print("\n--- Auto Configured Values ---")
    print(f"embedding.batch_size = {config.embedding_batch_size}")
    print(f"indexing.parse_workers = {config.parse_workers}")
    print(f"indexing.commit_batch_files = {config.commit_batch_files}")

if __name__ == "__main__":
    main()
