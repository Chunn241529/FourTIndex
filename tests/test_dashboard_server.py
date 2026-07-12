import json
import urllib.request
import urllib.error
import threading
import socket
import pytest

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
    server = dashboard_server.create_dashboard_server(free_port)
    t = threading.Thread(
        target=server.serve_forever,
        daemon=True
    )
    t.start()
    try:
        url = f"http://127.0.0.1:{free_port}/api/sessions"
        req = urllib.request.urlopen(url, timeout=5)
        assert req.status == 200
        body = req.read().decode("utf-8")
        data = json.loads(body)
        assert isinstance(data, list)

        url = f"http://127.0.0.1:{free_port}/api/session-details?id=dummy&agent=antigravity"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(url, timeout=5)
        assert exc_info.value.code in (404, 500)

        url = f"http://127.0.0.1:{free_port}/api/clean-mem"
        req = urllib.request.urlopen(
            urllib.request.Request(url, method="POST"), timeout=10
        )
        assert req.status == 200
        body = req.read().decode("utf-8")
        data = json.loads(body)
        assert data["success"] is True
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
    assert not t.is_alive()
