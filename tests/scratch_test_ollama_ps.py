import json
import urllib.request
import urllib.error

def main():
    url = "http://localhost:11434/api/ps"
    print(f"Querying Ollama loaded models at {url}...")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
            print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error querying Ollama: {e}")

if __name__ == "__main__":
    main()
