import sys
import os
import json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.config import Config
from src.lmstudio_client import LMStudioClient

def main():
    config = Config()
    client = LMStudioClient(config)
    res = client.list_models()
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
