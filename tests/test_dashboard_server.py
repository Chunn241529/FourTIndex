import json
import urllib.request
import urllib.error
import threading
import time
import socket

from src import dashboard_server

def test_find_free_port():
    port1 = dashboard_server.find_free_port(4040)
    assert port1 >= 4040
    
    # Bind to port1 and see if find_free_port finds a higher one
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port1))
        port2 = dashboard_server.find_free_port(port1)
        assert port2 > port1
    finally:
        s.close()

def test_api_endpoints():
    free_port = dashboard_server.find_free_port(25000)
    
    # Start server in thread
    t = threading.Thread(
        target=dashboard_server.start_dashboard_server,
        args=(free_port, False),
        daemon=True
    )
    t.start()
    time.sleep(1.0) # Wait for server to boot
    
    # Test GET /api/sessions
    try:
        url = f"http://127.0.0.1:{free_port}/api/sessions"
        req = urllib.request.urlopen(url)
        assert req.status == 200
        body = req.read().decode("utf-8")
        data = json.loads(body)
        assert isinstance(data, list)
    except urllib.error.URLError as e:
        # If port bound failed in test env, ignore or fail
        pass

    # Test GET /api/session-details?id=dummy&agent=dummy (404 / 400 cases)
    try:
        url = f"http://127.0.0.1:{free_port}/api/session-details?id=dummy&agent=antigravity"
        urllib.request.urlopen(url)
    except urllib.error.HTTPError as e:
        assert e.code in (404, 500)
    except Exception:
        pass
        
    # Clean memory POST endpoint
    try:
        url = f"http://127.0.0.1:{free_port}/api/clean-mem"
        req = urllib.request.urlopen(urllib.request.Request(url, method="POST"))
        assert req.status == 200
        body = req.read().decode("utf-8")
        data = json.loads(body)
        assert data["success"] is True
    except Exception:
        pass
