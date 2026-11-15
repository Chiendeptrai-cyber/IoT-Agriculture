"""Network Connection Controller for Edge -> Server link simulation.

Simulates network failures between the Edge Gateway and Central Server while keeping
the Sensor -> Edge (MQTT) link active.

Provides:
1. In-process Requests Simulation Adapter (`ConnectionSimulationAdapter`) for unit/integration tests.
2. Lightweight standalone HTTP Reverse Proxy (`ConnectionProxyServer`) for multi-process CLI testing.
3. IPC state persistence (`.network_state.json`) for cross-process CLI control.
"""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, Optional, Tuple
import urllib.request
import urllib.error

import requests
from requests.adapters import HTTPAdapter
from requests.models import Response
from urllib3.util import parse_url

LOG = logging.getLogger("network_simulator.controller")
DEFAULT_STATE_FILE = Path(__file__).resolve().parent / ".network_state.json"


class ConnectionState:
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    TIMEOUT = "TIMEOUT"
    SERVER_ERROR = "SERVER_ERROR"
    LATENCY = "LATENCY"


class ConnectionController:
    """Manages the simulated network link state between Edge and Server."""

    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = Path(state_file or DEFAULT_STATE_FILE)
        self.lock = threading.RLock()
        self._history: list[dict] = []
        self._load_or_init()

    def _load_or_init(self):
        with self.lock:
            if self.state_file.exists():
                try:
                    data = json.loads(self.state_file.read_text(encoding="utf-8"))
                    self.state = data.get("state", ConnectionState.ONLINE)
                    self.reason = data.get("reason", "initial")
                    self.latency = float(data.get("latency", 0.0))
                    self.last_updated = data.get("last_updated", datetime.now(timezone.utc).isoformat())
                    return
                except Exception:
                    pass
            self.state = ConnectionState.ONLINE
            self.reason = "initialized"
            self.latency = 0.0
            self.last_updated = datetime.now(timezone.utc).isoformat()
            self._save()

    def _save(self):
        payload = {
            "state": self.state,
            "reason": self.reason,
            "latency": self.latency,
            "last_updated": self.last_updated,
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._history.append(payload)

    def is_online(self) -> bool:
        """Return True if network link is currently operational."""
        with self.lock:
            self._load_or_init()
            return self.state == ConnectionState.ONLINE

    def connect(self, reason: str = "network restored") -> Dict[str, Any]:
        """Restore network connectivity."""
        with self.lock:
            self.state = ConnectionState.ONLINE
            self.reason = reason
            self.latency = 0.0
            self.last_updated = datetime.now(timezone.utc).isoformat()
            self._save()
            LOG.info("NETWORK LINK CONNECTED: %s", reason)
            return self.status()

    def disconnect(self, reason: str = "simulated network outage", mode: str = ConnectionState.OFFLINE) -> Dict[str, Any]:
        """Sever network connectivity to simulate an outage."""
        with self.lock:
            self.state = mode
            self.reason = reason
            self.last_updated = datetime.now(timezone.utc).isoformat()
            self._save()
            LOG.info("NETWORK LINK DISCONNECTED (%s): %s", mode, reason)
            return self.status()

    def set_timeout_mode(self, reason: str = "simulated packet loss / timeout") -> Dict[str, Any]:
        return self.disconnect(reason=reason, mode=ConnectionState.TIMEOUT)

    def set_server_error_mode(self, reason: str = "simulated 503 database failure") -> Dict[str, Any]:
        return self.disconnect(reason=reason, mode=ConnectionState.SERVER_ERROR)

    def set_latency(self, delay_seconds: float, reason: str = "simulated degraded link") -> Dict[str, Any]:
        with self.lock:
            self.state = ConnectionState.LATENCY
            self.latency = max(0.0, float(delay_seconds))
            self.reason = reason
            self.last_updated = datetime.now(timezone.utc).isoformat()
            self._save()
            LOG.info("NETWORK LINK LATENCY set to %.2fs: %s", self.latency, reason)
            return self.status()

    def status(self) -> Dict[str, Any]:
        """Inspect current link state."""
        with self.lock:
            self._load_or_init()
            return {
                "state": self.state,
                "is_online": self.state == ConnectionState.ONLINE,
                "reason": self.reason,
                "latency_seconds": self.latency,
                "last_updated": self.last_updated,
                "state_file": str(self.state_file),
            }

    def create_adapter(self, target_host: Optional[str] = None) -> "ConnectionSimulationAdapter":
        """Create a requests HTTPAdapter attached to this controller."""
        return ConnectionSimulationAdapter(self, target_host=target_host)


class ConnectionSimulationAdapter(HTTPAdapter):
    """A requests HTTPAdapter that intercepts traffic and enforces link state."""

    def __init__(self, controller: ConnectionController, target_host: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.controller = controller
        self.target_host = target_host

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        status = self.controller.status()
        state = status["state"]

        if state == ConnectionState.OFFLINE:
            raise requests.exceptions.ConnectionError(
                f"Simulated network outage (Connection refused): {status['reason']}"
            )
        elif state == ConnectionState.TIMEOUT:
            raise requests.exceptions.Timeout(
                f"Simulated network timeout (Packet drop): {status['reason']}"
            )
        elif state == ConnectionState.SERVER_ERROR:
            resp = Response()
            resp.status_code = 503
            resp.reason = "Service Unavailable (Simulated Outage)"
            resp.url = request.url
            resp.headers["Retry-After"] = "2"
            resp.headers["Content-Type"] = "application/json"
            resp._content = json.dumps({"detail": "Database unavailable (simulated)"}).encode("utf-8")
            return resp
        elif state == ConnectionState.LATENCY and status.get("latency_seconds", 0) > 0:
            time.sleep(status["latency_seconds"])

        return super().send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies)


class ProxyHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler that routes requests or enforces network cuts."""

    controller: ConnectionController
    target_base_url: str

    def log_message(self, format, *args):
        # Suppress noisy standard HTTP logs unless debugging
        pass

    def _proxy(self, method: str):
        status = self.controller.status()
        state = status["state"]

        if state == ConnectionState.OFFLINE:
            # Cut TCP connection abruptly or return 502/504
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Edge to Server connection severed (simulated network outage)"}')
            return

        elif state == ConnectionState.TIMEOUT:
            time.sleep(min(5.0, self.server.timeout or 3.0))
            self.send_response(504)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Simulated Gateway Timeout"}')
            return

        elif state == ConnectionState.SERVER_ERROR:
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", "2")
            self.end_headers()
            self.wfile.write(b'{"error": "Simulated Server Error (503)"}')
            return

        if state == ConnectionState.LATENCY and status.get("latency_seconds", 0) > 0:
            time.sleep(status["latency_seconds"])

        target_url = f"{self.target_base_url}{self.path}"
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        req = urllib.request.Request(target_url, data=body, method=method)
        for key, val in self.headers.items():
            if key.lower() not in ("host", "content-length"):
                req.add_header(key, val)

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                self.send_response(resp.status)
                for header, val in resp.getheaders():
                    self.send_header(header, val)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as exc:
            self.send_response(exc.code)
            for header, val in exc.headers.items():
                self.send_header(header, val)
            self.end_headers()
            self.wfile.write(exc.read())
        except Exception as exc:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"Upstream proxy failed: {exc}"}).encode())

    def do_GET(self):
        self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")

    def do_PUT(self):
        self._proxy("PUT")


class ConnectionProxyServer:
    """Standalone HTTP Proxy Server that drops or forwards requests based on controller state."""

    def __init__(self, port: int = 8008, target_url: str = "http://127.0.0.1:8000", controller: Optional[ConnectionController] = None):
        self.port = port
        self.target_url = target_url.rstrip("/")
        self.controller = controller or ConnectionController()
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        handler_cls = type("ConfiguredProxyHandler", (ProxyHandler,), {
            "controller": self.controller,
            "target_base_url": self.target_url,
        })
        self._server = HTTPServer(("127.0.0.1", self.port), handler_cls)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        LOG.info("Connection Proxy listening on 127.0.0.1:%d -> upstream %s", self.port, self.target_url)

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        LOG.info("Connection Proxy stopped.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="Print current network status")
    parser.add_argument("--connect", action="store_true", help="Restore Edge -> Server network")
    parser.add_argument("--disconnect", action="store_true", help="Sever Edge -> Server network")
    parser.add_argument("--mode", choices=["OFFLINE", "TIMEOUT", "SERVER_ERROR"], default="OFFLINE")
    parser.add_argument("--latency", type=float, help="Simulate network latency in seconds")
    parser.add_argument("--reason", default="manual CLI command")
    parser.add_argument("--proxy", action="store_true", help="Run HTTP proxy on port 8008")
    parser.add_argument("--port", type=int, default=8008)
    parser.add_argument("--target", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    controller = ConnectionController()

    if args.status:
        print(json.dumps(controller.status(), indent=2))
        return

    if args.connect:
        result = controller.connect(reason=args.reason)
        print("Connected:", json.dumps(result, indent=2))
        return

    if args.disconnect:
        result = controller.disconnect(reason=args.reason, mode=args.mode)
        print(f"Disconnected ({args.mode}):", json.dumps(result, indent=2))
        return

    if args.latency is not None:
        result = controller.set_latency(args.latency, reason=args.reason)
        print("Latency set:", json.dumps(result, indent=2))
        return

    if args.proxy:
        proxy = ConnectionProxyServer(port=args.port, target_url=args.target, controller=controller)
        proxy.start()
        print(f"Network Simulation Proxy running on http://127.0.0.1:{args.port} -> {args.target}")
        print("Use another terminal to run `python network-simulator/connection_controller.py --disconnect` or `--connect`.")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\nStopping proxy...")
        finally:
            proxy.stop()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
