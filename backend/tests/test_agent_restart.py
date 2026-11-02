"""Real local processes with a fake HTTP Gateway, no external inference."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from test_app import photo


def test_agent_http_bridge_crash_restart_retains_preview(tmp_path):
    root = Path(__file__).resolve().parents[2]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    release = threading.Event()
    invoked = threading.Event()
    receipt = {}

    class FakeGateway(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                assert self.path == "/v1/responses"
                assert self.headers["Authorization"] == "Bearer offline-gateway"
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert request["model"] == "openclaw/lut-color"
                session = self.headers["x-openclaw-session-key"]
                with httpx.Client(base_url=origin, timeout=5) as backend:
                    response = backend.post("/internal/openclaw/invoke", headers={"Authorization": "Bearer offline-bridge"}, json={
                        "agent_id": "lut-color", "runtime_session": session, "call_id": "offline-call",
                        "tool": "lut_preview", "arguments": {"preset_id": "warm"}})
                    response.raise_for_status()
                    receipt.update(response.json())
                    receipt["session"] = session
                invoked.set()
                release.wait(10)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "completed", "id": "offline-run", "output": []}).encode())
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    gateway = ThreadingHTTPServer(("127.0.0.1", 0), FakeGateway)
    thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    thread.start()
    env = {**os.environ, "DATA_DIR": str(tmp_path), "SESSION_SECRET": "restart-agent-test",
           "AGENT_RUNTIME": "openclaw", "OPENCLAW_GATEWAY_URL": f"http://127.0.0.1:{gateway.server_port}",
           "OPENCLAW_GATEWAY_TOKEN": "offline-gateway", "OPENCLAW_BRIDGE_TOKEN": "offline-bridge",
           "OPENCLAW_AGENT_ID": "lut-color", "OPENCLAW_VERIFIED_VERSION": "offline-http-fixture",
           "OPENCLAW_COMPATIBILITY_VERIFIED": "true", "AGENT_TIMEOUT": "30"}
    command = [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(root / "backend"),
               "--host", "127.0.0.1", "--port", str(port)]
    client = httpx.Client(base_url=origin, timeout=5)
    process = None

    def launch():
        proc = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if client.get("/api/health").status_code == 200:
                    return proc
            except httpx.TransportError:
                pass
            if proc.poll() is not None:
                raise RuntimeError("Disposable server exited")
            time.sleep(.05)
        proc.kill()
        proc.wait()
        raise TimeoutError("Disposable server start timed out")

    try:
        process = launch()
        client.post("/internal/openclaw/hello", headers={"Authorization": "Bearer offline-bridge"},
                    json={"agent_id": "lut-color", "runtime_version": "offline-http-fixture"}).raise_for_status()
        p = client.post("/api/projects", json={"name": "offline process test"}).json()
        p = client.post(f"/api/projects/{p['id']}/assets", files={"files": ("photo.png", photo(), "image/png")}).json()["project"]
        body = {"context_revision": p["revision"], "text": "暖一点", "request_id": "restart-once-only"}
        response = client.post(f"/api/projects/{p['id']}/instructions", json=body)
        response.raise_for_status()
        tid = response.json()["id"]
        assert invoked.wait(5)
        oid = receipt["operation_id"]
        for _ in range(100):
            op = client.get(f"/api/operations/{oid}").json()
            if op["status"] == "ready":
                break
            time.sleep(.02)
        assert op["status"] == "ready"
        process.kill()
        process.wait(timeout=5)
        release.set()
        process = launch()
        restored = client.get("/api/agent-turns/" + tid).json()
        assert restored["status"] == "interrupted" and restored["operation_id"] == oid
        assert client.get(f"/api/operations/{oid}").json()["status"] == "ready"
        assert client.post(f"/api/projects/{p['id']}/instructions", json=body).json()["id"] == tid
        late = client.post("/internal/openclaw/invoke", headers={"Authorization": "Bearer offline-bridge"}, json={
            "agent_id": "lut-color", "runtime_session": receipt["session"], "call_id": "late-call",
            "tool": "lut_preview", "arguments": {"preset_id": "mono"}})
        assert late.status_code == 409
        after = client.get(f"/api/projects/{p['id']}").json()
        assert len(after["operations"]) == 1 and after["assets"][0]["revision"] == 0
        client.post(f"/api/operations/{oid}/apply").raise_for_status()
        for _ in range(100):
            applied = client.get(f"/api/operations/{oid}").json()
            if applied["status"] == "succeeded":
                break
            time.sleep(.02)
        assert applied["status"] == "succeeded"
        assert client.get(applied["download_url"]).status_code == 200
    finally:
        release.set()
        client.close()
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        gateway.shutdown()
        gateway.server_close()
