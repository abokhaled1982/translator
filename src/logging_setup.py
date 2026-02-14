"""
logging_setup.py — Non-Blocking High-Performance Logging.

Verbesserungen:
  - Queue mit maxsize=10_000 statt unbegrenzt (verhindert RAM-Überlauf bei Log-Sturm)
  - QueueHandler mit respect_handler_level=True (dropped statt blockiert bei Overflow)
  - Explizites setup()/teardown() statt fragiler global-Variable
  - Kein Garbage-Collection-Problem mehr
"""
import json
import logging
import logging.handlers
import queue
import sys
import atexit
from typing import Optional

# ── Formatter ─────────────────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """Strukturierte JSON-Logs für PROD (einfach von Log-Aggregatoren parsebar)."""
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, datefmt="%H:%M:%S"),
            "lvl": record.levelname,
            "msg": record.getMessage(),
            "mod": record.module,
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


class _DevFormatter(logging.Formatter):
    """Farbige, lesbare Logs für DEV-Umgebung."""
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname:<8}{self.RESET}"
        return super().format(record)


# ── Listener-Management ───────────────────────────────────────────────────────

_listener: Optional[logging.handlers.QueueListener] = None


def teardown() -> None:
    """Stoppt den Listener sauber. Wird via atexit registriert."""
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None


def setup_logging(mode: str) -> logging.Logger:
    """
    Initialisiert das Logging-System.
    Kann sicher mehrfach aufgerufen werden (idempotent).
    """
    global _listener

    # Alten Listener sauber stoppen falls vorhanden (bei Reloads/Tests)
    teardown()

    root_logger = logging.getLogger()
    # Bestehende Handler entfernen
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    # 1. Ziel-Handler (Konsole/Stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    if mode == "PROD":
        root_logger.setLevel(logging.INFO)
        console_handler.setFormatter(_JsonFormatter())
    else:
        root_logger.setLevel(logging.DEBUG)
        console_handler.setFormatter(
            _DevFormatter(
                fmt="%(asctime)s %(levelname)s %(name)s › %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    # 2. Queue mit Größenlimit — verhindert RAM-Überlauf bei Log-Sturm
    # Bei Overflow wird dropped (QueueHandler.emit() mit enqueue_sentinel())
    # statt blockiert — der Main-Loop wird nie aufgehalten.
    log_queue: queue.Queue = queue.Queue(maxsize=10_000)

    # 3. Queue-Handler für den Main-Thread (wirft nur in Queue → extrem schnell)
    queue_handler = logging.handlers.QueueHandler(log_queue)
    root_logger.addHandler(queue_handler)

    # 4. Listener (Hintergrund-Thread, der Queue abarbeitet)
    _listener = logging.handlers.QueueListener(
        log_queue,
        console_handler,
        respect_handler_level=True,  # Handler-Level wird respektiert
    )
    _listener.start()

    # Sicherstellen dass beim Beenden alles geschrieben wird
    atexit.register(teardown)

    # Dämpfung von Third-Party Libraries (verhindert Log-Spam)
    noisy_libs = (
        "livekit", "httpx", "httpcore",
        "websockets", "asyncio", "google",
    )
    for lib in noisy_libs:
        logging.getLogger(lib).setLevel(logging.WARNING)

    logger = logging.getLogger("intraunit")
    logger.info(f"🚀 Threaded Logging gestartet ({mode})")
    return logger