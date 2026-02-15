"""
health.py — Professional HTTP Health Check für Docker / Kubernetes.

Features:
  - Separate Liveness & Readiness Probes
  - Startup Probe für langsam startende Apps
  - Metrics Endpoint (optional)
  - Graceful Shutdown Support
  - Thread-sicher, non-blocking

Endpunkte:
  GET /health/live    → 200 OK wenn Prozess läuft (Liveness Probe)
  GET /health/ready   → 200 OK wenn Session bereit (Readiness Probe)
  GET /health/startup → 200 OK wenn Initial-Setup fertig (Startup Probe)
  GET /metrics        → Prometheus-Format Metriken (optional)
  GET /               → Legacy 200 OK (deprecated)

K8s-Konfiguration:
  startupProbe:   GET /health/startup  (für langsamen Start)
  livenessProbe:  GET /health/live     (Prozess lebt)
  readinessProbe: GET /health/ready    (Traffic-Ready)
"""
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar, Dict, Any

logger = logging.getLogger("intraunit.health")


# ── Global State ──────────────────────────────────────────────────────────────
class _HealthState:
    """Thread-sicherer globaler Gesundheitszustand."""
    
    _lock = threading.Lock()
    
    # States
    _alive = True      # Prozess läuft (Liveness)
    _ready = False     # Session ist bereit für Traffic (Readiness)
    _startup = False   # Initial-Setup abgeschlossen (Startup)
    
    # Metrics
    _start_time = time.time()
    _total_sessions = 0
    _active_sessions = 0
    _failed_sessions = 0
    
    @classmethod
    def set_alive(cls, value: bool) -> None:
        with cls._lock:
            cls._alive = value
    
    @classmethod
    def set_ready(cls, value: bool) -> None:
        with cls._lock:
            cls._ready = value
            if value:
                cls._active_sessions += 1
            else:
                cls._active_sessions = max(0, cls._active_sessions - 1)
    
    @classmethod
    def set_startup(cls, value: bool) -> None:
        with cls._lock:
            cls._startup = value
    
    @classmethod
    def is_alive(cls) -> bool:
        with cls._lock:
            return cls._alive
    
    @classmethod
    def is_ready(cls) -> bool:
        with cls._lock:
            return cls._ready
    
    @classmethod
    def is_startup_complete(cls) -> bool:
        with cls._lock:
            return cls._startup
    
    @classmethod
    def increment_sessions(cls) -> None:
        with cls._lock:
            cls._total_sessions += 1
    
    @classmethod
    def increment_failures(cls) -> None:
        with cls._lock:
            cls._failed_sessions += 1
    
    @classmethod
    def get_metrics(cls) -> Dict[str, Any]:
        """Gibt Metriken für Monitoring zurück."""
        with cls._lock:
            uptime = time.time() - cls._start_time
            return {
                "uptime_seconds": uptime,
                "total_sessions": cls._total_sessions,
                "active_sessions": cls._active_sessions,
                "failed_sessions": cls._failed_sessions,
                "alive": cls._alive,
                "ready": cls._ready,
                "startup_complete": cls._startup,
            }


# ── HTTP Handler ──────────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    """HTTP Request Handler für Health Checks."""
    
    # Paths
    LIVE_PATH: ClassVar[str] = "/health/live"
    READY_PATH: ClassVar[str] = "/health/ready"
    STARTUP_PATH: ClassVar[str] = "/health/startup"
    METRICS_PATH: ClassVar[str] = "/metrics"
    LEGACY_PATHS: ClassVar[set] = {"/", "/health"}  # Deprecated
    
    def do_GET(self) -> None:
        """Handler für GET-Requests."""
        
        # Liveness Probe
        if self.path == self.LIVE_PATH:
            if _HealthState.is_alive():
                self._respond(200, b"ALIVE")
            else:
                self._respond(503, b"DEAD")
        
        # Readiness Probe
        elif self.path == self.READY_PATH:
            if _HealthState.is_ready():
                self._respond(200, b"READY")
            else:
                self._respond(503, b"NOT READY")
        
        # Startup Probe
        elif self.path == self.STARTUP_PATH:
            if _HealthState.is_startup_complete():
                self._respond(200, b"STARTUP COMPLETE")
            else:
                self._respond(503, b"STARTING")
        
        # Metrics
        elif self.path == self.METRICS_PATH:
            metrics = _HealthState.get_metrics()
            self._respond_metrics(metrics)
        
        # Legacy Endpoints (deprecated)
        elif self.path in self.LEGACY_PATHS:
            if _HealthState.is_alive():
                self._respond(200, b"OK")
            else:
                self._respond(503, b"UNHEALTHY")
        
        # 404
        else:
            self._respond(404, b"NOT FOUND")
    
    def _respond(self, code: int, body: bytes) -> None:
        """Sendet einfache Text-Response."""
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)
    
    def _respond_metrics(self, metrics: Dict[str, Any]) -> None:
        """Sendet Prometheus-Format Metriken."""
        lines = [
            "# HELP agent_uptime_seconds Time since agent started",
            "# TYPE agent_uptime_seconds gauge",
            f"agent_uptime_seconds {metrics['uptime_seconds']:.2f}",
            "",
            "# HELP agent_sessions_total Total number of sessions",
            "# TYPE agent_sessions_total counter",
            f"agent_sessions_total {metrics['total_sessions']}",
            "",
            "# HELP agent_sessions_active Currently active sessions",
            "# TYPE agent_sessions_active gauge",
            f"agent_sessions_active {metrics['active_sessions']}",
            "",
            "# HELP agent_sessions_failed Total failed sessions",
            "# TYPE agent_sessions_failed counter",
            f"agent_sessions_failed {metrics['failed_sessions']}",
            "",
            "# HELP agent_alive Liveness state (1=alive, 0=dead)",
            "# TYPE agent_alive gauge",
            f"agent_alive {1 if metrics['alive'] else 0}",
            "",
            "# HELP agent_ready Readiness state (1=ready, 0=not_ready)",
            "# TYPE agent_ready gauge",
            f"agent_ready {1 if metrics['ready'] else 0}",
            "",
        ]
        
        body = "\n".join(lines).encode("utf-8")
        
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)
    
    def log_message(self, *_) -> None:
        """Kein Log-Spam durch K8s-Probes."""
        pass


# ── Server ────────────────────────────────────────────────────────────────────
_server: HTTPServer | None = None


def start(host: str = "0.0.0.0", port: int = 8080) -> None:
    """
    Startet den Health-Check-Server als Daemon-Thread (non-blocking).
    
    Args:
        host: Bind-Address (default: 0.0.0.0 für alle Interfaces)
        port: Port (default: 8080)
    """
    global _server
    
    def _run() -> None:
        global _server
        try:
            _server = HTTPServer((host, port), _Handler)
            logger.info(f"✓ Health-Check Server läuft auf {host}:{port}")
            logger.info(f"  Liveness:  http://{host}:{port}/health/live")
            logger.info(f"  Readiness: http://{host}:{port}/health/ready")
            logger.info(f"  Startup:   http://{host}:{port}/health/startup")
            logger.info(f"  Metrics:   http://{host}:{port}/metrics")
            _server.serve_forever()
        except OSError as e:
            logger.error(f"❌ Health-Check Server konnte nicht starten: {e}")
    
    thread = threading.Thread(target=_run, daemon=True, name="health-check")
    thread.start()


def stop() -> None:
    """Stoppt den Health-Check-Server gracefully."""
    global _server
    if _server:
        logger.info("Stopping health check server...")
        _server.shutdown()
        _server = None


# ── Public API ────────────────────────────────────────────────────────────────

def mark_ready() -> None:
    """
    Setzen wenn Session erfolgreich aufgebaut wurde (Readiness Probe).
    K8s beginnt Traffic zu routen.
    """
    _HealthState.set_ready(True)
    _HealthState.increment_sessions()
    logger.info("✅ Agent als READY markiert")


def mark_not_ready() -> None:
    """
    Setzen während Session-Aufbau, bei Reconnect oder nach Call-Ende.
    K8s stoppt Traffic zu diesem Pod.
    """
    _HealthState.set_ready(False)
    logger.info("⏸️  Agent als NOT READY markiert")


def mark_startup_complete() -> None:
    """
    Setzen nach erfolgreichem Initial-Setup.
    K8s beginnt mit Liveness/Readiness Checks.
    """
    _HealthState.set_startup(True)
    logger.info("✅ Startup abgeschlossen")


def mark_unhealthy() -> None:
    """
    Setzt Liveness auf False — Kubernetes wird den Pod neu starten.
    Nur bei kritischen, unbehebbaren Fehlern verwenden!
    """
    _HealthState.set_alive(False)
    logger.critical("💀 Agent als UNHEALTHY (dead) markiert — Pod-Restart empfohlen")


def mark_healthy() -> None:
    """
    Setzt Liveness zurück auf True.
    Normalerweise nicht nötig, da initial True.
    """
    _HealthState.set_alive(True)
    logger.info("✅ Agent als HEALTHY (alive) markiert")


def increment_failure() -> None:
    """
    Erhöht Fehler-Counter.
    Für Monitoring & Alerting.
    """
    _HealthState.increment_failures()
    logger.debug("Failed session counter incremented")


def get_metrics() -> Dict[str, Any]:
    """
    Gibt aktuelle Metriken zurück.
    
    Returns:
        Dict mit uptime, sessions, states, etc.
    """
    return _HealthState.get_metrics()
