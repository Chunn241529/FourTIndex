import sys
import os
import json
import urllib.request
import urllib.error

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.config import Config
from src.lmstudio_client import LMStudioClient

def main():
    config = Config()
    client = LMStudioClient(config)
    
    loaded = client.list_models()
    models_data = loaded.get("models", []) or loaded.get("data", [])
    
    print("--- Listing loaded models and unloading them (using only instance_id) ---")
    for m in models_data:
        key = m.get("key") or m.get("id")
        instances = m.get("loaded_instances", [])
        if instances:
            print(f"Model {key} has {len(instances)} loaded instances:")
            for inst in instances:
                inst_id = inst.get("id") or inst.get("instance_identifier")
                print(f"  Unloading instance: {inst_id} for model {key}...")
                
                # Directly construct the request with only instance_id
                url = f"{client.host.rstrip('/')}/api/v1/models/unload"
                headers = {"Content-Type": "application/json"}
                if client.api_token:
                    headers["Authorization"] = f"Bearer {client.api_token}"
                
                payload = {"instance_id": inst_id}
                req_data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
                
                try:
                    with urllib.request.urlopen(req, timeout=30) as response:
                        res = json.loads(response.read().decode("utf-8"))
                        print(f"  Result: {json.dumps(res)}")
                except Exception as e:
                    print(f"  Error: {e}")
        else:
            print(f"Model {key} is not loaded.")

if __name__ == "__main__":
    main()
