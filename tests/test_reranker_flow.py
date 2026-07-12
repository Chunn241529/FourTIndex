import time
from src.config import Config
from src.reranker import LocalReranker

def test_flow():
    config = Config()
    print("=== INITIALIZING LOCAL RERANKER ===")
    print(f"Model: {config.rerank_model}")
    print(f"Rerank Enabled: {config.rerank_enabled}")
    print(f"Candidates Limit: {config.rerank_candidates_limit}")
    
    start_init = time.time()
    reranker = LocalReranker(config)
    
    # Sample query and chunks
    query = "How to load a model in LM Studio?"
    
    chunks = [
        {
            "content": "To download a model from Hugging Face, click on the search tab and type the repository name.",
            "metadata": {"file": "download.py"}
        },
        {
            "content": "To load a model into memory in LM Studio, send a POST request to /api/v1/models/load with the model ID and context_length.",
            "metadata": {"file": "load_model.py"}
        },
        {
            "content": "FourTIndex is a high-fidelity local codebase indexer and Model Context Protocol (MCP) server.",
            "metadata": {"file": "about.py"}
        }
    ]
    
    print("\n=== RUNNING RERANK ===")
    print(f"Query: '{query}'")
    print("Input Chunks (in order):")
    for i, c in enumerate(chunks):
        print(f"  {i+1}. [{c['metadata']['file']}] {c['content'][:60]}...")
        
    rerank_start = time.time()
    results = reranker.rerank(query, chunks, top_k=3)
    duration = time.time() - rerank_start
    total_duration = time.time() - start_init
    
    print(f"\nRerank completed in {duration:.4f} seconds (Total execution including init: {total_duration:.2f}s).")
    print("\nReranked Results (highest relevance first):")
    for i, r in enumerate(results):
        score = r.get("rerank_score", 0.0)
        print(f"  {i+1}. Score: {score:.4f} | [{r['metadata']['file']}] {r['content']}")

if __name__ == "__main__":
    test_flow()
