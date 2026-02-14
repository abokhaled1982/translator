"""
health.py — Schlanker HTTP-Health-Check für Docker / Kubernetes.
Läuft als Daemon-Thread, blockiert den Event-Loop nicht.

Endpunkte:
  GET /             → 200 OK  (legacy, identisch zu /health/live)
  GET /health       → 200 OK  (legacy)
  GET /health/live  → 200 OK  wenn Prozess läuft (Liveness Probe)
  GET /health/ready → 200 OK  wenn Session aufgebaut ist (Readiness Probe)
  Alle anderen      → 503     (unhealthy)

K8s-Konfiguration:
  livenessProbe:  GET /health/live
  readinessProbe: GET /health/ready
"""
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

logger = logging.getLogger("intraunit.health")


class _HealthState:
    """Thread-sicherer globaler Gesundheitszustand mit Liveness/Readiness-Trennung."""
    _lock = threading.Lock()
    _alive = True    # Prozess läuft (Liveness)
    _ready = False   # Session ist aufgebaut und bereit für Traffic (Readiness)

    @classmethod
    def set_alive(cls, value: bool) -> None:
        with cls._lock:
            cls._alive = value

    @classmethod
    def set_ready(cls, value: bool) -> None:
        with cls._lock:
            cls._ready = value

    @classmethod
    def is_alive(cls) -> bool:
        with cls._lock:
            return cls._alive

    @classmethod
    def is_ready(cls) -> bool:
        with cls._lock:
            return cls._ready

    @classmethod
    def is_healthy(cls) -> bool:
        """Legacy: beide Zustände müssen true sein."""
        with cls._lock:
            return cls._alive and cls._ready


class _Handler(BaseHTTPRequestHandler):
    # Legacy-Pfade (Liveness)
    LIVE_PATHS: ClassVar[set] = {"/", "/health", "/health/live"}
    READY_PATH: ClassVar[str] = "/health/ready"

    def do_GET(self) -> None:
        if self.path == self.READY_PATH:
            if _HealthState.is_ready():
                self._respond(200, b"READY")
            else:
                self._respond(503, b"NOT READY")
        elif self.path in self.LIVE_PATHS:
            if _HealthState.is_alive():
                self._respond(200, b"OK")
            else:
                self._respond(503, b"DEAD")
        else:
            self._respond(404, b"NOT FOUND")

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


# ── Öffentliche API ───────────────────────────────────────────────────────────

def mark_ready() -> None:
    """Setzen wenn Session erfolgreich aufgebaut wurde (Readiness Probe)."""
    _HealthState.set_ready(True)
    logger.info("Agent als READY markiert")


def mark_not_ready() -> None:
    """Setzen während Session-Aufbau oder bei Reconnect."""
    _HealthState.set_ready(False)
    logger.warning("Agent als NOT READY markiert")


def mark_unhealthy() -> None:
    """Setzt Liveness auf False — Kubernetes wird den Pod neu starten."""
    _HealthState.set_alive(False)
    logger.critical("Agent als UNHEALTHY (dead) markiert")


def mark_healthy() -> None:
    """Setzt Liveness zurück auf True."""
    _HealthState.set_alive(True)
    logger.info("Agent als HEALTHY (alive) markiert")