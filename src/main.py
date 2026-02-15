"""
main.py — Einstiegspunkt des Intraunit Voice Agents.

Starten:
  python main.py dev    → DEV:  lokaler Room, Mikrofon/Lautsprecher
  python main.py prod   → PROD: LiveKit Worker, JSON-Logs

Verbesserungen:
  - SIGTERM-Handler fuer graceful Shutdown (Docker stop, K8s rolling update)
  - Sauberes HTTP-Client-Teardown beim Beenden
  - Vereinfachtes Mode-Handling ohne Anti-Pattern
"""
import sys
import os
import signal
import asyncio

# ── Pfad-Fix ──────────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── 1. Modus aus CLI-Argument ─────────────────────────────────────────────────
_RAW = sys.argv[1].lower() if len(sys.argv) > 1 else "dev"

if _RAW in ("prod", "start"):
    _MODE = "PROD"
    sys.argv[1] = "start"
elif _RAW in ("dev", "console"):
    _MODE = "DEV"
    sys.argv[1] = "dev"
else:
    print(f"[FEHLER] Unbekannter Modus: '{_RAW}'. Erlaubt: dev | prod", file=sys.stderr)
    sys.exit(1)

# ── 2. Imports ────────────────────────────────────────────────────────────────
import plugin_patch  # Muss VOR allen livekit-Imports stehen — behebt 1008-Bug
from logging_setup import setup_logging, teardown as logging_teardown
from config import CONFIG
import health
from agent import entrypoint
from tools import close_http_client
from livekit.agents import cli, WorkerOptions

CONFIG.mode = _MODE

# ── 3. Logging + Validierung ──────────────────────────────────────────────────
logger = setup_logging(_MODE)
logger.info(f"Intraunit Agent startet | Modus: {_MODE}")
logger.info(f"Modell: {CONFIG.voice.model} | Stimme: {CONFIG.voice.voice}")

try:
    CONFIG.validate()
except EnvironmentError as e:
    logger.critical(str(e))
    sys.exit(1)

# ── 4. Health-Check starten ───────────────────────────────────────────────────
health.start(host=CONFIG.server.host, port=CONFIG.server.health_port)
logger.info(f"Health-Check auf Port {CONFIG.server.health_port}")
# Prozess laeuft (liveness=true), aber noch nicht bereit fuer Traffic
# health.mark_ready() wird in agent.py nach erfolgreichem Session-Start aufgerufen

# ── 5. Graceful Shutdown via SIGTERM ─────────────────────────────────────────
def _handle_sigterm(sig, frame) -> None:
    """
    Wird von Docker stop / K8s rolling update ausgeloest.
    Markiert den Agent als nicht-ready damit kein neuer Traffic kommt.
    """
    logger.info("SIGTERM empfangen — graceful shutdown eingeleitet")
    health.mark_not_ready()
    health.mark_unhealthy()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(close_http_client())
        else:
            loop.run_until_complete(close_http_client())
    except Exception as e:
        logger.warning(f"HTTP-Client Teardown Fehler: {e}")

    logging_teardown()
    sys.exit(0)


signal.signal(signal.SIGTERM, _handle_sigterm)

# ── 6. LiveKit Worker ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
    except KeyboardInterrupt:
        logger.info("Agent beendet (Strg+C).")
    except Exception as e:
        health.mark_unhealthy()
        logger.critical(f"Kritischer Fehler im Main-Loop: {e}", exc_info=True)
        sys.exit(1)
    finally:
        try:
            asyncio.get_event_loop().run_until_complete(close_http_client())
        except Exception:
            pass
        logging_teardown()
