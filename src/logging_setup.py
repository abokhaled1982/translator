"""
logging_setup.py — Strukturiertes Logging.
PROD: JSON (maschinenlesbar, kein stdout-Rauschen)
DEV:  Lesbares Format mit Farben
"""
import json
import logging
import os
import sys


class _JsonFormatter(logging.Formatter):
    """Kompaktes JSON-Format für PROD / Log-Aggregatoren (Datadog, CloudWatch etc.)."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "msg": record.getMessage(),
            "mod": record.module,
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


class _DevFormatter(logging.Formatter):
    """Farbiges, lesbares Format für die Entwicklungskonsole."""

    COLORS = {
        "DEBUG":    "\033[36m",   # Cyan
        "INFO":     "\033[32m",   # Grün
        "WARNING":  "\033[33m",   # Gelb
        "ERROR":    "\033[31m",   # Rot
        "CRITICAL": "\033[35m",   # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname:<8}{self.RESET}"
        return super().format(record)


def setup_logging(mode: str) -> logging.Logger:
    """
    Richtet Logging ein und gibt den App-Logger zurück.
    Unterdrückt noisy Third-Party-Logger (livekit, httpx, websockets).
    """
    logger = logging.getLogger("intraunit")
    logger.handlers.clear()
    logger.propagate = False

    handler = logging.StreamHandler()

    if mode == "PROD":
        logger.setLevel(logging.INFO)
        handler.stream = sys.stdout
        handler.setFormatter(_JsonFormatter())

        # PROD: stdout nach dem Logger-Setup auf /dev/null — kein print()-Rauschen
        import io
        sys.stdout = io.TextIOWrapper(open(os.devnull, "wb"))

    else:
        logger.setLevel(logging.DEBUG)
        handler.setFormatter(_DevFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s › %(message)s",
            datefmt="%H:%M:%S",
        ))

    logger.addHandler(handler)

    # Noisy Libraries dämpfen
    for noisy in ("livekit", "httpx", "httpcore", "websockets", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logger
