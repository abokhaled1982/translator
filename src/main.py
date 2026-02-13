"""
main.py — Einstiegspunkt des Intraunit Voice Agents.

Starten (immer vom Projekt-Root, also dem translator/ Ordner):
  python main.py dev    → DEV:  lokaler Room, Mikrofon/Lautsprecher
  python main.py prod   → PROD: LiveKit Worker, JSON-Logs
"""
import sys
import os

# ── Pfad-Fix: src/ zum Python-Suchpfad hinzufügen ────────────────────────────
# Damit funktionieren: from logging_setup import ..., from config import ...
# egal ob du von translator/ oder von translator/src/ aus startest.
_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC  = os.path.join(_ROOT, "src")
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

# ── 2. Imports (jetzt findet Python die Module in src/) ───────────────────────
from logging_setup import setup_logging   # src/logging_setup.py
from config import CONFIG                 # src/config.py
import health                             # src/health.py
from agent import entrypoint              # src/agent.py
from livekit.agents import cli, WorkerOptions

# Modus ins Config-Objekt schreiben (frozen dataclass → via object.__setattr__)
object.__setattr__(CONFIG, "mode", _MODE)

# ── 3. Logging + Validierung ──────────────────────────────────────────────────
logger = setup_logging(_MODE)
logger.info(f"Intraunit Agent startet | Modus: {_MODE}")

try:
    CONFIG.validate()
except EnvironmentError as e:
    logger.critical(str(e))
    sys.exit(1)

# ── 4. Health-Check (Daemon-Thread, blockiert nicht) ─────────────────────────
health.start(host=CONFIG.server.host, port=CONFIG.server.health_port)

# ── 5. LiveKit Worker ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
    except KeyboardInterrupt:
        logger.info("Agent beendet (Strg+C).")
    except Exception as e:
        health.mark_unhealthy()
        logger.critical(f"Kritischer Fehler im Main-Loop: {e}", exc_info=True)
        sys.exit(1)
