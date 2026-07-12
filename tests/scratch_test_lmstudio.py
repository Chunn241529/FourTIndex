import sys
import os
import json

# Ensure the root directory is in the path so we can import src
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.config import Config
from src.lmstudio_client import LMStudioClient

def get_running_models(client: LMStudioClient):
    res = client.list_models()
    if "error" in res:
        print(f"Error listing models: {res['error']}")
        return []
    
    running = []
    models = res.get("models", [])
    for m in models:
        # A model is running if it has loaded_instances
        if m.get("loaded_instances"):
            running.append(m)
    return running

def main():
    config = Config()
    client = LMStudioClient(config)
    print(f"Connecting to LM Studio at {client.host}...")
    
    running = get_running_models(client)
    print(f"\n--- Currently running models ({len(running)}): ---")
    for m in running:
        print(f"- {m.get('display_name')} ({m.get('key')}) - Type: {m.get('type')}")
        
    if len(running) < 3:
        print("\nLess than 3 models are currently running. Let's try loading 'monas' to make it 3...")
        # Check if 'monas' is available to be loaded
        all_models = client.list_models().get("models", [])
        available_keys = [m.get("key") for m in all_models]
        
        target_model = "monas"
        if target_model in available_keys:
            print(f"Loading '{target_model}'...")
            load_res = client.load_model(target_model)
            print(f"Load response: {json.dumps(load_res, indent=2)}")
            
            # Re-fetch running models
            running = get_running_models(client)
            print(f"\n--- Updated running models ({len(running)}): ---")
            for m in running:
                print(f"- {m.get('display_name')} ({m.get('key')}) - Type: {m.get('type')}")
        else:
            print(f"Model '{target_model}' is not available in LM Studio's list.")

if __name__ == "__main__":
    main()
