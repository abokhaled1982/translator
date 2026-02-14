"""
main.py — Einstiegspunkt des Intraunit Voice Agents.

Starten (immer vom Projekt-Root):
  python main.py dev    → DEV:  lokaler Room, Mikrofon/Lautsprecher
  python main.py prod   → PROD: LiveKit Worker, JSON-Logs

Verbesserungen:
  - SIGTERM-Handler für graceful Shutdown (Docker stop, K8s rolling update)
  - health.mark_ready() nach erfolgreichem Setup (Readiness Probe)
  - Sauberes HTTP-Client-Teardown beim Beenden
  - mode direkt in AppConfig ohne object.__setattr__() Anti-Pattern
"""
import sys
import os
import signal
import asyncio

# ── Pfad-Fix: src/ zum Python-Suchpfad hinzufügen ────────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

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
from logging_setup import setup_logging, teardown as logging_teardown
from config import CONFIG
import health
from agent import entrypoint
from tools import close_http_client
from livekit.agents import cli, WorkerOptions

# Modus setzen (AppConfig ist jetzt nicht mehr frozen — kein Anti-Pattern)
CONFIG.mode = _MODE

# ── 3. Logging + Validierung ──────────────────────────────────────────────────
logger = setup_logging(_MODE)
logger.info(f"Intraunit Agent startet | Modus: {_MODE}")

try:
    CONFIG.validate()
except EnvironmentError as e:
    logger.critical(str(e))
    sys.exit(1)

# ── 4. Health-Check starten ───────────────────────────────────────────────────
health.start(host=CONFIG.server.host, port=CONFIG.server.health_port)
# Prozess läuft, aber Session noch nicht aufgebaut → noch nicht READY
# health.mark_ready() wird nach erfolgreichem Session-Start aufgerufen
# (kann in agent.py entrypoint eingebaut werden)

# ── 5. Graceful Shutdown via SIGTERM ─────────────────────────────────────────
def _handle_sigterm(sig, frame) -> None:
    """
    Wird von Docker stop / K8s rolling update ausgelöst.
    Markiert den Agent als nicht-ready damit kein neuer Traffic kommt,
    dann wartet K8s auf terminationGracePeriodSeconds bevor SIGKILL.
    """
    logger.info("SIGTERM empfangen — graceful shutdown eingeleitet")
    health.mark_not_ready()
    health.mark_unhealthy()

    # HTTP-Client asynchron schließen
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(close_http_client())
        else:
            loop.run_until_complete(close_http_client())
    except Exception as e:
        logger.warning(f"HTTP-Client konnte nicht sauber geschlossen werden: {e}")

    # Logging sauber beenden (Queue leeren)
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
        # Cleanup beim normalen Beenden
        try:
            asyncio.get_event_loop().run_until_complete(close_http_client())
        except Exception:
            pass
        logging_teardown()