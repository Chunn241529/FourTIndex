import http.server
import socketserver
import webbrowser
import urllib.parse
import json
import threading
import os
import socket
from typing import Any

from src.config import Config
from src.token_meter import (
    discover_antigravity_sessions,
    discover_claude_sessions,
    discover_codex_sessions,
    get_pricing
)
from src.context_auditor import (
    audit_antigravity_session,
    audit_claude_session,
    audit_codex_session,
    get_recommendations,
    generate_local_bridge
)

class DashboardHTTPHandler(http.server.BaseHTTPRequestHandler):
    config: Config = None

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress logging request noise to stdout/stderr
        pass

    def send_json(self, data: Any, status: int = 200) -> None:
        try:
            content = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            # Catch broken pipe/connection errors gracefully
            pass

    def send_html(self, html_content: str, status: int = 200) -> None:
        try:
            content = html_content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            pass

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        if path in ("/", "/index.html"):
            current_dir = os.path.dirname(os.path.abspath(__file__))
            html_path = os.path.join(current_dir, "dashboard", "index.html")
            
            if not os.path.exists(html_path):
                # Simple fallback UI if file doesn't exist
                self.send_html("<html><body><h1>Dashboard HTML file not found</h1></body></html>", status=404)
                return
                
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            self.send_html(html_content)
            
        elif path == "/api/sessions":
            # Gather all sessions from all discoverers
            candidates = []
            try:
                candidates.extend(discover_antigravity_sessions())
            except Exception:
                pass
            try:
                candidates.extend(discover_claude_sessions())
            except Exception:
                pass
            try:
                candidates.extend(discover_codex_sessions())
            except Exception:
                pass

            # Sort by modification time (newest first)
            candidates.sort(key=lambda c: c.modified_at, reverse=True)

            sessions = []
            for c in candidates:
                try:
                    snapshot = c.parser(c.path, c.conversation_id)
                    total_prompt = snapshot.total_prompt
                    total_completion = snapshot.total_completion
                    total_cost = (
                        total_prompt * get_pricing(snapshot.model)[0] +
                        total_completion * get_pricing(snapshot.model)[1]
                    ) / 1_000_000.0
                    model = snapshot.model
                except Exception:
                    total_prompt, total_completion, total_cost = 0, 0, 0.0
                    model = "unknown"

                sessions.append({
                    "id": c.conversation_id,
                    "agent": c.agent,
                    "path": c.path,
                    "modified_at": c.modified_at,
                    "model": model,
                    "total_prompt": total_prompt,
                    "total_completion": total_completion,
                    "total_cost": total_cost,
                })
            self.send_json(sessions)

        elif path == "/api/session-details":
            sess_id = query.get("id", [""])[0]
            agent = query.get("agent", [""])[0]
            
            if not sess_id or not agent:
                self.send_json({"error": "Missing 'id' or 'agent' query parameter"}, status=400)
                return

            # Find matching candidate
            candidates = []
            if agent == "antigravity":
                candidates = discover_antigravity_sessions()
            elif agent == "claude":
                candidates = discover_claude_sessions()
            elif agent == "codex":
                candidates = discover_codex_sessions()

            target = next((c for c in candidates if c.conversation_id == sess_id), None)
            if not target:
                self.send_json({"error": f"Session {sess_id} not found for agent {agent}"}, status=404)
                return

            try:
                # Perform the turn audit
                if agent == "antigravity":
                    audit_data = audit_antigravity_session(target.path, target.conversation_id)
                elif agent == "claude":
                    audit_data = audit_claude_session(target.path, target.conversation_id)
                else:
                    audit_data = audit_codex_session(target.path, target.conversation_id)

                if not audit_data:
                    self.send_json({"error": "Failed to audit session transcript"}, status=500)
                    return

                recommendations = get_recommendations(audit_data.get("turns", []))
                bridge_summary = generate_local_bridge(audit_data, self.config, use_llm=False)

                result = {
                    "agent": audit_data.get("agent"),
                    "model": audit_data.get("model"),
                    "conversation_id": audit_data.get("conversation_id"),
                    "turns": audit_data.get("turns", []),
                    "modified_files": audit_data.get("modified_files", []),
                    "recommendations": recommendations,
                    "bridge_summary": bridge_summary
                }
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": f"Error performing audit: {str(e)}"}, status=500)

        elif path == "/api/lmstudio/models":
            try:
                from src.lmstudio_client import LMStudioClient
                client = LMStudioClient(self.config)
                res = client.list_models()
                if "error" in res:
                    self.send_json(res, status=500)
                else:
                    self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)

        elif path == "/api/lmstudio/download/status":
            try:
                from src.lmstudio_client import LMStudioClient
                client = LMStudioClient(self.config)
                res = client.get_download_status()
                if "error" in res:
                    self.send_json(res, status=500)
                else:
                    self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        if path == "/api/clean-mem":
            try:
                from src.setup_ollama import unload_models
                unload_models()
                
                from src.token_meter import evaluate_latest_session
                report = evaluate_latest_session()
                
                self.send_json({
                    "success": True,
                    "message": "Successfully unloaded all models from Ollama VRAM/RAM.",
                    "report": report
                })
            except Exception as e:
                self.send_json({"success": False, "message": str(e)}, status=500)
                
        elif path == "/api/generate-bridge":
            sess_id = query.get("id", [""])[0]
            agent = query.get("agent", [""])[0]
            use_llm = query.get("use_llm", ["false"])[0].lower() == "true"

            if not sess_id or not agent:
                self.send_json({"error": "Missing 'id' or 'agent' query parameter"}, status=400)
                return

            candidates = []
            if agent == "antigravity":
                candidates = discover_antigravity_sessions()
            elif agent == "claude":
                candidates = discover_claude_sessions()
            elif agent == "codex":
                candidates = discover_codex_sessions()

            target = next((c for c in candidates if c.conversation_id == sess_id), None)
            if not target:
                self.send_json({"error": f"Session {sess_id} not found"}, status=404)
                return

            try:
                if agent == "antigravity":
                    audit_data = audit_antigravity_session(target.path, target.conversation_id)
                elif agent == "claude":
                    audit_data = audit_claude_session(target.path, target.conversation_id)
                else:
                    audit_data = audit_codex_session(target.path, target.conversation_id)

                bridge_summary = generate_local_bridge(audit_data, self.config, use_llm=use_llm)
                self.send_json({"bridge_summary": bridge_summary})
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)
        elif path in ("/api/lmstudio/load", "/api/lmstudio/unload", "/api/lmstudio/download", "/api/lmstudio/chat"):
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
                data = json.loads(body) if body else {}
                
                from src.lmstudio_client import LMStudioClient
                client = LMStudioClient(self.config)
                
                if path == "/api/lmstudio/load":
                    model = data.get("model")
                    if not model:
                        self.send_json({"error": "Missing 'model' parameter"}, status=400)
                        return
                    ctx_len = data.get("context_length")
                    res = client.load_model(model, context_length=ctx_len, extra_config=data.get("extra_config"))
                elif path == "/api/lmstudio/unload":
                    model = data.get("model")
                    if not model:
                        self.send_json({"error": "Missing 'model' parameter"}, status=400)
                        return
                    instance_id = data.get("instance_id")
                    if not instance_id:
                        loaded = client.list_models()
                        if "data" in loaded:
                            for m in loaded["data"]:
                                if m.get("id") == model:
                                    instance_id = m.get("instance_identifier") or m.get("instance_id")
                                    break
                    res = client.unload_model(model, instance_id=instance_id)
                elif path == "/api/lmstudio/download":
                    model = data.get("model")
                    if not model:
                        self.send_json({"error": "Missing 'model' parameter"}, status=400)
                        return
                    res = client.download_model(model)
                else: # /api/lmstudio/chat
                    model = data.get("model")
                    message = data.get("message")
                    if not model or not message:
                        self.send_json({"error": "Missing 'model' or 'message' parameter"}, status=400)
                        return
                    ctx_len = data.get("context_length")
                    res = client.chat(model, message, context_length=ctx_len)
                
                if "error" in res:
                    self.send_json(res, status=500)
                else:
                    self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)
        else:
            self.send_response(404)
            self.end_headers()

def find_free_port(start_port: int) -> int:
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except socket.error:
                port += 1
    return start_port

def start_dashboard_server(port: int = 4040, open_browser: bool = True) -> None:
    config = Config()
    free_port = find_free_port(port)
    
    if open_browser:
        def open_web() -> None:
            import time
            time.sleep(0.8)
            webbrowser.open(f"http://localhost:{free_port}")
        threading.Thread(target=open_web, daemon=True).start()
        
    server_address = ("127.0.0.1", free_port)
    
    class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        
    class CustomHandler(DashboardHTTPHandler):
        def __init__(self, *args: Any, **kwargs: Any):
            self.config = config
            super().__init__(*args, **kwargs)
            
    httpd = ThreadedHTTPServer(server_address, CustomHandler)
    print(f"============================================================")
    print(f"🚀 FourTIndex Token Dashboard running at http://localhost:{free_port}")
    print(f"Press Ctrl+C to stop the dashboard server.")
    print(f"============================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        httpd.shutdown()
        print("Dashboard server stopped.")
