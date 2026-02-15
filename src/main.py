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
import atexit

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
# WICHTIG: plugin_patch MUSS VOR allen livekit-Imports stehen
import plugin_patch  # Behebt 1008-Bug bei Gemini Function Calling

from logging_setup import setup_logging, teardown as logging_teardown
from config import CONFIG
import health
from agent import entrypoint
from tools import close_http_client
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

# Initial State: Prozess läuft (liveness=true), aber noch nicht ready
# health.mark_ready() wird in agent.py nach erfolgreichem Session-Start aufgerufen
health.mark_startup_complete()

# ── 5. Graceful Shutdown Handler ──────────────────────────────────────────────
_shutdown_initiated = False


def _graceful_shutdown(sig, frame) -> None:
    """
    Graceful Shutdown bei SIGTERM (Docker stop) oder SIGINT (Strg+C).
    
    Flow:
      1. Mark as not ready → K8s stoppt Traffic
      2. Wait for active sessions (bis timeout)
      3. Cleanup resources
      4. Exit
    """
    global _shutdown_initiated
    
    if _shutdown_initiated:
        logger.warning("⚠️  Shutdown bereits eingeleitet...")
        return
    
    _shutdown_initiated = True
    
    signal_name = "SIGTERM" if sig == signal.SIGTERM else "SIGINT"
    logger.info(f"🛑 {signal_name} empfangen — Graceful Shutdown eingeleitet")
    
    # 1. Als not-ready markieren → kein neuer Traffic
    health.mark_not_ready()
    
    # 2. Kurz warten damit aktive Sessions enden können
    logger.info(f"⏳ Warte {CONFIG.server.shutdown_timeout_s}s auf aktive Sessions...")
    
    try:
        loop = asyncio.get_event_loop()
        
        # HTTP Client schließen
        if loop.is_running():
            loop.create_task(close_http_client())
        else:
            loop.run_until_complete(close_http_client())
        
        logger.info("✓ HTTP Client geschlossen")
    
    except Exception as e:
        logger.warning(f"⚠️  HTTP-Client Teardown Fehler: {e}")
    
    # 3. Logging sauber beenden
    logging_teardown()
    
    # 4. Health Server stoppen
    health.stop()
    
    logger.info("👋 Shutdown abgeschlossen")
    sys.exit(0)


# Signal Handler registrieren
signal.signal(signal.SIGTERM, _graceful_shutdown)
signal.signal(signal.SIGINT, _graceful_shutdown)

# Auch atexit als Fallback
atexit.register(lambda: _graceful_shutdown(None, None) if not _shutdown_initiated else None)

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
        logger.info("⌨️  Agent beendet (Strg+C)")
        _graceful_shutdown(signal.SIGINT, None)
    
    except Exception as e:
        health.mark_unhealthy()
        health.increment_failure()
        logger.critical(
            f"💥 Kritischer Fehler im Main-Loop: {type(e).__name__}: {e}",
            exc_info=True
        )
        sys.exit(1)
    
    finally:
        # Final Cleanup
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(close_http_client())
            else:
                loop.run_until_complete(close_http_client())
        except Exception:
            pass
        
        logging_teardown()
        health.stop()
