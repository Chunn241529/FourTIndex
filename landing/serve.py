import http.server
import socketserver
import webbrowser
import os
import sys

PORT = 8000
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

# Print a nice banner
print("=" * 60)
print("🚀 FourTIndex Landing Page Server 🚀")
print("=" * 60)
print(f"Local server directory: {DIRECTORY}")
print(f"Running locally at: http://localhost:{PORT}")
print("Press Ctrl+C to stop the server.")
print("=" * 60)

# Open web browser
try:
    webbrowser.open(f"http://localhost:{PORT}")
except Exception as e:
    print(f"Could not open browser automatically: {e}")

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Stopping server. Goodbye!")
        sys.exit(0)
