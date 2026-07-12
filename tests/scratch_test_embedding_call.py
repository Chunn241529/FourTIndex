import sys
import os
import json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.config import Config
from src.lmstudio_client import LMStudioClient

def main():
    config = Config()
    client = LMStudioClient(config)
    
    test_texts = ["Hello world", "Test sentence"]
    
    # 1. Test with configured name
    model_config = config.lmstudio_embedding_model
    print(f"Testing embedding with configured model name: '{model_config}'...")
    res = client.embeddings(model_config, test_texts)
    print("Response:", json.dumps(res, indent=2))
    
    # 2. Test with exact key if different
    exact_key = "text-embedding-monas-embeddings-text-code"
    if model_config != exact_key:
        print(f"\nTesting embedding with exact key: '{exact_key}'...")
        res_exact = client.embeddings(exact_key, test_texts)
        print("Response:", json.dumps(res_exact, indent=2))

if __name__ == "__main__":
    main()
