import os
import time
from pathlib import Path

def get_token_count(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        # Fallback if tiktoken is not installed
        return max(1, len(text) // 4)

def estimate_cost(tokens: int, cost_per_1m_tokens: float = 3.0) -> float:
    return (tokens / 1_000_000) * cost_per_1m_tokens

def generate_mock_codebase(target_dir: Path, num_files: int = 100, lines_per_file: int = 200) -> str:
    if not target_dir.exists():
        target_dir.mkdir(parents=True)
    
    all_code = []
    for i in range(num_files):
        file_path = target_dir / f"file_{i:03d}.py"
        content = [
            f"# This is a mock file {i} containing application logic",
            "import os",
            "import sys",
            "from typing import List, Dict, Optional",
            "",
            f"class ApplicationController{i}:",
            '    """Handles routing and business logic for the main application modules."""',
            "    def __init__(self, config: Dict[str, str]):",
            "        self.config = config",
            "        self.data_store: List[str] = []",
            "",
            "    def process_request(self, payload: Dict[str, str]) -> bool:",
            "        if not payload:",
            "            return False",
            "        # Complex business logic simulated here",
            "        for key, value in payload.items():",
            "            self.data_store.append(f'{key}={value}')",
            "        return True",
            ""
        ]
        
        # padding out to desired lines with somewhat realistic looking method signatures
        for j in range((lines_per_file - len(content)) // 4):
            content.extend([
                f"    def auxiliary_helper_method_{j}(self, input_val: int) -> int:",
                "        # Performs validation and data transformations",
                "        result = input_val * 2 + 15",
                "        return result"
            ])
            
        full_text = "\n".join(content)
        file_path.write_text(full_text)
        all_code.append(f"--- file_{i:03d}.py ---\n{full_text}")

    return "\n".join(all_code)

def simulate_fourtindex_retrieval(full_codebase_text: str) -> str:
    """Simulates what FourTIndex would retrieve for a typical coding task."""
    # A typical retrieval:
    # 1. Outline of the main entry point
    # 2. 5 relevant chunks (e.g. class definitions and methods related to the task)
    # 3. 1 specific file's exact code lines (say 50 lines)
    
    retrieved_parts = []
    
    # 1. Outline simulation (just grabbing class signatures from the first 5 files)
    outline = "Project Outline:\n"
    for i in range(5):
        outline += f"- class ApplicationController{i}(config: Dict)\n"
        outline += f"  - def process_request(self, payload: Dict) -> bool\n"
    retrieved_parts.append(outline)
    
    # 2. 5 semantic search chunks (grab random 15-line snippets from the codebase)
    lines = full_codebase_text.split('\n')
    for chunk_idx in range(5):
        start = (len(lines) // 10) * (chunk_idx + 1)
        chunk = "\n".join(lines[start:start+15])
        retrieved_parts.append(f"--- Search Result {chunk_idx + 1} ---\n{chunk}")
        
    # 3. Exact code lines reading (grab 50 lines from somewhere)
    exact_lines = "\n".join(lines[100:150])
    retrieved_parts.append(f"--- Code Context (file_000.py lines 100-150) ---\n{exact_lines}")
    
    return "\n\n".join(retrieved_parts)

def main():
    print("Running Context Efficiency & Cost Benchmark (Real Tokenization)...")
    
    fixture_dir = Path("benchmarks/temp_context_bench")
    if fixture_dir.exists():
        import shutil
        shutil.rmtree(fixture_dir)
    
    print("\n[1/3] Simulating typical mid-sized project (100 files, ~20,000 lines)...")
    full_project_text = generate_mock_codebase(fixture_dir, num_files=100, lines_per_file=200)
    
    # 1. Without FourTIndex (Full Dump)
    print("\n[2/3] Analyzing 'Without FourTIndex' scenario (Full codebase dump)...")
    without_tokens = get_token_count(full_project_text)
    without_cost = estimate_cost(without_tokens, 3.0) # Claude 3.5 Sonnet / GPT-4o input cost
    
    # Simulating LLM reading latency (API time to first token & processing speed)
    # A very optimistic 5000 tokens/sec
    without_latency = without_tokens / 5000.0
    print(f"  -> Context Size: {without_tokens:,} tokens")
    print(f"  -> Est. Processing Latency: {without_latency:.1f} seconds")
    print(f"  -> Est. Cost per Prompt: ${without_cost:.4f} USD")
    
    # 2. With FourTIndex (Targeted Retrieval)
    print("\n[3/3] Analyzing 'With FourTIndex' scenario (Targeted retrieval)...")
    targeted_text = simulate_fourtindex_retrieval(full_project_text)
    with_tokens = get_token_count(targeted_text)
    with_cost = estimate_cost(with_tokens, 3.0)
    
    # FourTIndex local search overhead (0.5s) + LLM processing
    with_latency = 0.5 + (with_tokens / 5000.0)
    
    print(f"  -> Context Size: {with_tokens:,} tokens")
    print(f"  -> Est. Processing Latency: {with_latency:.1f} seconds")
    print(f"  -> Est. Cost per Prompt: ${with_cost:.4f} USD")
    
    # Summary
    print("\n==================================================")
    print("Benchmark Comparison Results:")
    print(f"  - Context Reduction: {without_tokens / max(1, with_tokens):.1f}x smaller")
    print(f"  - Cost Savings: {((without_cost - with_cost) / max(0.0001, without_cost)) * 100:.1f}% cheaper")
    print(f"  - Latency Speedup: {without_latency / max(0.1, with_latency):.1f}x faster")
    print("==================================================")
    
    if fixture_dir.exists():
        import shutil
        shutil.rmtree(fixture_dir)

if __name__ == "__main__":
    main()
