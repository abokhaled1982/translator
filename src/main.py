"""
main.py — Professional Production Entry Point.

Features:
  - Graceful Shutdown (SIGTERM, SIGINT)
  - Sauberes Resource Management
  - Health Check Integration
  - Metrics Support
  - Error Recovery
  - Structured Logging

Starten:
  python main.py dev    → DEV:  lokaler Room, Mikrofon/Lautsprecher, farbige Logs
  python main.py prod   → PROD: LiveKit Worker, JSON-Logs, Metrics

Docker:
  docker run intraunit-agent  → PROD-Modus (default)
"""
import sys
import os
import signal
import asyncio

# ── Pfad-Fix ──────────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── 1. Modus aus CLI-Argument oder ENV ───────────────────────────────────────
_RAW = sys.argv[1].lower() if len(sys.argv) > 1 else os.getenv("AGENT_MODE", "prod").lower()

if _RAW in ("prod", "start", "production"):
    _MODE = "PROD"
    if len(sys.argv) > 1:
        sys.argv[1] = "start"
elif _RAW in ("dev", "console", "development"):
    _MODE = "DEV"
    if len(sys.argv) > 1:
        sys.argv[1] = "dev"
else:
    print(
        f"[FEHLER] Unbekannter Modus: '{_RAW}'\n"
        "Erlaubt: dev | prod\n"
        "Usage: python main.py [dev|prod]",
        file=sys.stderr
    )
    sys.exit(1)

# ── 2. Imports ────────────────────────────────────────────────────────────────

from logging_setup import setup_logging, teardown as logging_teardown
from config import CONFIG
import health
from agent import entrypoint
from livekit.agents import cli, WorkerOptions

CONFIG.mode = _MODE

# ── 3. Logging + Validierung ──────────────────────────────────────────────────
logger = setup_logging(_MODE, CONFIG)

logger.info("╔════════════════════════════════════════════════════════════╗")
logger.info(f"║  IntraUnit Voice Agent v1.0                                ║")
logger.info(f"║  Mode: {_MODE:<50} ║")
logger.info("╚════════════════════════════════════════════════════════════╝")

logger.info(f"🤖 Agent: {CONFIG.agent.agent_name} von {CONFIG.agent.company_name}")
logger.info(f"🎙️  Modell: {CONFIG.voice.model}")
logger.info(f"🗣️  Stimme: {CONFIG.voice.voice}")
logger.info(f"🌡️  Temperature: {CONFIG.voice.temperature}")

try:
    CONFIG.validate()
    logger.info("✅ Konfiguration validiert")
except EnvironmentError as e:
    logger.critical(f"❌ Konfigurationsfehler: {e}")
    sys.exit(1)

# ── 4. Health-Check Server starten ────────────────────────────────────────────
health.start(host=CONFIG.server.health_host, port=CONFIG.server.health_port)

# Initial State: Prozess läuft, startup fertig, ready für neue Sessions
health.mark_startup_complete()
health.mark_ready()

# ── 5. Graceful Shutdown Handler ──────────────────────────────────────────────
_shutdown_initiated = False


def _graceful_shutdown(sig, frame) -> None:
    """
    Graceful Shutdown bei SIGTERM (Docker stop) oder SIGINT (Strg+C).
    
    Flow:
      1. Mark as not ready → K8s stoppt Traffic
      2. Close HTTP resources (sync)
      3. Stop health server
      4. Teardown logging
    """
    global _shutdown_initiated
    
    if _shutdown_initiated:
        return
    
    _shutdown_initiated = True
    
    signal_name = (
        "SIGTERM" if sig == signal.SIGTERM
        else "SIGINT" if sig == signal.SIGINT
        else "atexit"
    )
    logger.info(f"🛑 {signal_name} empfangen — Graceful Shutdown eingeleitet")
    
    # 1. Als not-ready markieren → kein neuer Traffic
    health.mark_not_ready()
    
    # 2. HTTP Client synchron schließen (Event loop ist ggf. schon zu)
    try:
        from tools import _http_client
        if _http_client is not None:
            # httpx.AsyncClient kann NICHT sicher sync geschlossen werden
            # wenn der Loop weg ist — einfach auf None setzen, GC räumt auf.
            import tools
            tools._http_client = None
            logger.info("✓ HTTP Client freigegeben")
    except Exception as e:
        logger.warning(f"⚠️  HTTP-Client Teardown Fehler: {e}")
    
    # 3. Health Server stoppen (idempotent)
    health.stop()
    
    # 4. Logging sauber beenden
    logging_teardown()
    
    logger.info("👋 Shutdown abgeschlossen")


# Signal Handler registrieren
signal.signal(signal.SIGTERM, _graceful_shutdown)
signal.signal(signal.SIGINT, _graceful_shutdown)

# ── 6. LiveKit Worker starten ─────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        logger.info("🚀 LiveKit Worker startet...")
        
        # Worker-Optionen
        worker_options = WorkerOptions(
            entrypoint_fnc=entrypoint,
            # Weitere Optionen je nach Bedarf:
            # ws_url=CONFIG.livekit_url,
            # api_key=CONFIG.livekit_api_key,
            # api_secret=CONFIG.livekit_api_secret,
        )
        
        # Worker starten (blocking)
        cli.run_app(worker_options)
    
    except KeyboardInterrupt:
        pass  # Signal handler already ran
    
    except Exception as e:
        health.mark_unhealthy()
        health.increment_failure()
        logger.critical(
            f"💥 Kritischer Fehler im Main-Loop: {type(e).__name__}: {e}",
            exc_info=True
        )
        sys.exit(1)
    
    finally:
        _graceful_shutdown(None, None)  # idempotent, no-op if already ran
