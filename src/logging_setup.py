"""
logging_setup.py — Professional Non-Blocking High-Performance Logging.

Features:
  - Queue-basiert mit maxsize (verhindert RAM-Überlauf)
  - QueueHandler mit respect_handler_level=True
  - Sentry Error Tracking Integration
  - Strukturierte JSON-Logs für Production
  - Farbige Logs für Development
  - Explizites setup()/teardown()
  - Thread-sicher und GC-sicher
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
    """Strukturierte JSON-Logs für PROD (Log-Aggregatoren)."""
    
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Extra context falls vorhanden
        if hasattr(record, "user_id"):
            entry["user_id"] = record.user_id
        if hasattr(record, "session_id"):
            entry["session_id"] = record.session_id
        if hasattr(record, "room_name"):
            entry["room_name"] = record.room_name
        
        # Exception-Handling
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(entry, ensure_ascii=False)


class _DevFormatter(logging.Formatter):
    """Farbige, lesbare Logs für Development."""
    
    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        
        # Level mit Farbe und Padding
        record.levelname = f"{color}{self.BOLD}{record.levelname:<8}{self.RESET}"
        
        # Logger-Name dimmen für bessere Lesbarkeit
        parts = record.name.split(".")
        if len(parts) > 1:
            record.name = f"{self.DIM}{'.'.join(parts[:-1])}.{self.RESET}{parts[-1]}"
        
        formatted = super().format(record)
        
        # Exception-Tracebacks in Rot
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            formatted += f"\n{self.COLORS['ERROR']}{exc_text}{self.RESET}"
        
        return formatted


# ── Sentry Integration ────────────────────────────────────────────────────────

def _setup_sentry(dsn: str, environment: str) -> None:
    """Initialisiert Sentry Error Tracking."""
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
        
        sentry_logging = LoggingIntegration(
            level=logging.INFO,        # Capture INFO and above
            event_level=logging.ERROR  # Send errors as events
        )
        
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=0.1,  # 10% Performance Monitoring
            profiles_sample_rate=0.1,
            integrations=[sentry_logging],
            attach_stacktrace=True,
            send_default_pii=False,  # DSGVO-konform
        )
        
        logging.getLogger("intraunit").info("✓ Sentry Error Tracking aktiviert")
    except ImportError:
        logging.getLogger("intraunit").warning(
            "⚠️  sentry-sdk nicht installiert (pip install sentry-sdk)"
        )
    except Exception as e:
        logging.getLogger("intraunit").error(
            f"❌ Sentry-Initialisierung fehlgeschlagen: {e}"
        )


# ── Listener-Management ───────────────────────────────────────────────────────

_listener: Optional[logging.handlers.QueueListener] = None
_log_queue: Optional[queue.Queue] = None


def teardown() -> None:
    """Stoppt den Listener sauber und flusht alle Logs."""
    global _listener, _log_queue
    
    if _listener is not None:
        try:
            # Alle verbleibenden Logs schreiben
            _listener.stop()
            _listener = None
        except Exception as e:
            print(f"Warning: Logging teardown error: {e}", file=sys.stderr)
    
    _log_queue = None


def setup_logging(mode: str, config) -> logging.Logger:
    """
    Initialisiert das Logging-System.
    Kann sicher mehrfach aufgerufen werden (idempotent).
    
    Args:
        mode: "DEV" oder "PROD"
        config: AppConfig-Instanz
    
    Returns:
        Logger-Instanz für "intraunit"
    """
    global _listener, _log_queue
    
    # Alten Listener sauber stoppen falls vorhanden
    teardown()
    
    root_logger = logging.getLogger()
    
    # Bestehende Handler entfernen
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    
    # 1. Log Level setzen
    log_level = getattr(logging, config.logging.level, logging.INFO)
    root_logger.setLevel(log_level)
    
    # 2. Formatter wählen
    if mode == "PROD" or config.logging.structured:
        formatter = _JsonFormatter()
    else:
        formatter = _DevFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s › %(message)s",
            datefmt="%H:%M:%S",
        )
    
    # 3. Console Handler konfigurieren
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)
    
    # 4. Queue mit Größenlimit (verhindert RAM-Überlauf bei Log-Sturm)
    _log_queue = queue.Queue(maxsize=config.logging.queue_size)
    
    # 5. Queue-Handler für Main-Thread (ultra-schnell, non-blocking)
    queue_handler = logging.handlers.QueueHandler(_log_queue)
    root_logger.addHandler(queue_handler)
    
    # 6. Listener (Hintergrund-Thread verarbeitet Queue)
    _listener = logging.handlers.QueueListener(
        _log_queue,
        console_handler,
        respect_handler_level=True,
    )
    _listener.start()
    
    # 7. Sicherstellen dass beim Beenden alles geschrieben wird
    atexit.register(teardown)
    
    # 8. Sentry Error Tracking (optional)
    if config.logging.sentry_dsn:
        _setup_sentry(
            config.logging.sentry_dsn,
            config.logging.sentry_environment
        )
    
    # 9. Dämpfung von Third-Party Libraries (verhindert Log-Spam)
    noisy_libs = (
        "livekit", "httpx", "httpcore",
        "websockets", "asyncio", "google",
        "urllib3", "h11", "hpack",
    )
    for lib in noisy_libs:
        logging.getLogger(lib).setLevel(logging.WARNING)
    
    # 10. Main Logger
    logger = logging.getLogger("intraunit")
    logger.info(
        f"🚀 Threaded Logging gestartet "
        f"[{mode}] [Level: {config.logging.level}] "
        f"[Queue: {config.logging.queue_size}]"
    )
    
    return logger


# ── Convenience Functions ─────────────────────────────────────────────────────

def add_context(logger: logging.Logger, **kwargs) -> logging.LoggerAdapter:
    """
    Fügt permanenten Context zu allen Logs hinzu.
    
    Usage:
        logger = add_context(logger, session_id="abc123", user_id="user_456")
        logger.info("Session started")  # enthält automatisch session_id + user_id
    """
    return logging.LoggerAdapter(logger, kwargs)


def get_logger(name: str) -> logging.Logger:
    """
    Holt einen Logger für ein bestimmtes Modul.
    
    Usage:
        logger = get_logger(__name__)
    """
    return logging.getLogger(f"intraunit.{name}")
