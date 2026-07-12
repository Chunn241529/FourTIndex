import sys
import os

# Ensure the root directory is in the path so we can import src
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.config import Config
from src.llm import LLMClient
from src.embedder import Embedder

def main():
    print("=== LOADING CONFIGURATION ===")
    local_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "config.yaml")
    config = Config(local_config_path)
    print(f"Loaded Config Path: {config.config_path}")
    print(f"Active Provider: {config.llm_provider.upper()}")
    
    if config.llm_provider == "lmstudio":
        print(f"Host: {config.lmstudio_host}")
        print(f"LLM Model: {config.lmstudio_llm_model}")
        print(f"Embedding Model: {config.lmstudio_embedding_model}")
    else:
        print(f"Host: {config.ollama_host}")
        print(f"LLM Model: {config.ollama_llm_model}")
        print(f"Embedding Model: {config.ollama_embedding_model}")

    print("\n=== TESTING EMBEDDING GENERATION ===")
    try:
        embedder = Embedder(config)
        test_text = "FourTIndex semantic search integration"
        embedding = embedder.get_embedding(test_text)
        print(f"Successfully generated embedding for: '{test_text}'")
        print(f"Embedding dimensions: {len(embedding)}")
        print(f"First 5 values: {embedding[:5]}")
    except Exception as e:
        print(f"Embedding Error: {e}")

    print("\n=== TESTING LLM GENERATION ===")
    try:
        llm = LLMClient(config)
        question = "What is FourTIndex?"
        context = "FourTIndex is a high-fidelity local codebase indexer and Model Context Protocol (MCP) server."
        print(f"Asking question: '{question}'")
        print(f"With context: '{context}'")
        answer = llm.generate_answer(question, context)
        print("\n--- LLM RESPONSE ---")
        print(answer)
    except Exception as e:
        print(f"LLM Error: {e}")

if __name__ == "__main__":
    main()
