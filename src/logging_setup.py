"""
logging_setup.py — Non-Blocking High-Performance Logging.

Optimierung:
  - Nutzt QueueHandler und QueueListener.
  - Der Main-Loop (Asyncio) wird NICHT durch I/O (print/write) blockiert.
  - Logs werden in einen separaten Thread ausgelagert.
"""
import json
import logging
import logging.handlers
import queue
import sys
import atexit

# Globale Referenz für den Listener, damit er nicht Garbage-collected wird
_listener = None

class _JsonFormatter(logging.Formatter):
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
    COLORS = {
        "DEBUG": "\033[36m", "INFO": "\033[32m",
        "WARNING": "\033[33m", "ERROR": "\033[31m", "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname:<8}{self.RESET}"
        return super().format(record)

def setup_logging(mode: str) -> logging.Logger:
    global _listener
    
    root_logger = logging.getLogger()
    root_logger.handlers = [] # Bestehende Handler löschen

    # 1. Das eigentliche Ziel (Konsole/Stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    if mode == "PROD":
        root_logger.setLevel(logging.INFO)
        console_handler.setFormatter(_JsonFormatter())
    else:
        root_logger.setLevel(logging.DEBUG)
        console_handler.setFormatter(_DevFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s › %(message)s",
            datefmt="%H:%M:%S"
        ))

    # 2. Die Queue (Puffer)
    log_queue = queue.Queue(-1) # Unendliche Größe

    # 3. Der Handler für den Main-Thread (wirft nur in Queue -> extrem schnell)
    queue_handler = logging.handlers.QueueHandler(log_queue)
    root_logger.addHandler(queue_handler)

    # 4. Der Listener (Hintergrund-Thread, der die Queue abarbeitet)
    _listener = logging.handlers.QueueListener(log_queue, console_handler)
    _listener.start()

    # Sicherstellen, dass beim Beenden alles geschrieben wird
    atexit.register(_listener.stop)

    # Dämpfung von Third-Party Libraries
    for noisy in ("livekit", "httpx", "httpcore", "websockets", "asyncio", "google"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logger = logging.getLogger("intraunit")
    logger.info(f"🚀 Threaded Logging gestartet ({mode})")
    return logger