"""
health.py — Schlanker HTTP-Health-Check für Docker / Kubernetes.
Läuft als Daemon-Thread, blockiert den Event-Loop nicht.
GET /        → 200 OK  (healthy)
GET /health  → 200 OK  (healthy)
Alle anderen → 503     (unhealthy)
"""
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

logger = logging.getLogger("intraunit.health")


class _HealthState:
    """Thread-sicherer globaler Gesundheitszustand."""
    _lock = threading.Lock()
    _healthy = True

    @classmethod
    def set(cls, value: bool) -> None:
        with cls._lock:
            cls._healthy = value

    @classmethod
    def is_healthy(cls) -> bool:
        with cls._lock:
            return cls._healthy


class _Handler(BaseHTTPRequestHandler):
    PATHS: ClassVar[set] = {"/", "/health"}

    def do_GET(self) -> None:
        if self.path in self.PATHS and _HealthState.is_healthy():
            self._respond(200, b"OK")
        else:
            self._respond(503, b"UNHEALTHY")

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Kein Log-Spam durch K8s-Probes
    def log_message(self, *_) -> None:
        pass


def start(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Startet den Health-Check-Server als Daemon-Thread (non-blocking)."""
    def _run() -> None:
        try:
            server = HTTPServer((host, port), _Handler)
            logger.info(f"Health-Check läuft auf {host}:{port}")
            server.serve_forever()
        except OSError as e:
            logger.error(f"Health-Check konnte nicht starten: {e}")

    thread = threading.Thread(target=_run, daemon=True, name="health-check")
    thread.start()


def mark_unhealthy() -> None:
    _HealthState.set(False)
    logger.critical("Agent als UNHEALTHY markiert")


def mark_healthy() -> None:
    _HealthState.set(True)
