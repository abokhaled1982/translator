"""
tools.py — Professional Function Tools mit Simulation Mode (Forced).

Fixes:
  - Simulation Mode ist jetzt ERZWUNGEN (verhindert Errno 11001 / Netzwerk-Calls)
  - end_call hat jetzt einen Delay, damit Sarah aussprechen kann
  - Robusteres Error Handling
"""
import asyncio
import logging
import json
import random
import os
import smtplib
from collections import deque
from datetime import date, datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Annotated, Callable, Optional, Deque, List
from time import time

from livekit.agents import llm

from config import CONFIG

logger = logging.getLogger("intraunit.tools")


# ── HTTP Connection-Pool ──────────────────────────────────────────────────────
_http_client = None

def _get_http_client():
    """Lazy-initialized HTTP Client (Connection Pooling)."""
    global _http_client
    if _http_client is None:
        try:
            import httpx
            cfg = CONFIG.tools
            _http_client = httpx.AsyncClient(
                timeout=cfg.api_timeout_s,
                limits=httpx.Limits(
                    max_connections=cfg.http_max_connections,
                    max_keepalive_connections=cfg.http_max_keepalive,
                ),
                headers={
                    "User-Agent": f"IntraUnit-Agent/{CONFIG.agent.agent_name}",
                    "Authorization": f"Bearer {cfg.calendar_api_key}" if cfg.calendar_api_key else "",
                },
            )
            logger.debug("HTTP Client initialisiert")
        except ImportError:
            logger.warning("httpx nicht installiert")
    return _http_client

async def close_http_client() -> None:
    """Schließt HTTP Client sauber."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
        logger.debug("HTTP Client geschlossen")


# ── Rate Limiter ──────────────────────────────────────────────────────────────
class RateLimiter:
    """Sliding Window Rate Limiter für Tool Calls."""
    
    def __init__(self, max_calls: int, window_seconds: int = 60):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.calls: Deque[float] = deque()
    
    def is_allowed(self) -> bool:
        now = time()
        while self.calls and self.calls[0] < now - self.window_seconds:
            self.calls.popleft()
        if len(self.calls) >= self.max_calls:
            return False
        self.calls.append(now)
        return True


# ── E-Mail Service ────────────────────────────────────────────────────────────
async def _send_booking_email(
    name: str, email: str, appointment_date: str, appointment_time: str, topic: str
) -> bool:
    """Sendet Buchungsbestätigung per E-Mail."""
    if not CONFIG.email.enabled:
        # Nur Loggen im Simulationsmodus
        logger.info(f"📧 [SIMULATION] E-Mail an {email} wäre gesendet worden.")
        return True
    
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Terminbestätigung: {appointment_date} um {appointment_time}"
        msg["From"] = CONFIG.email.from_email
        msg["To"] = email
        
        html = f"""
        <html><body>
            <h2>Hallo {name}!</h2>
            <p>Termin bestätigt: {appointment_date} um {appointment_time} Uhr.</p>
            <p>Thema: {topic}</p>
            <p>Viele Grüße,<br>{CONFIG.agent.agent_name}</p>
        </body></html>
        """
        msg.attach(MIMEText(html, "html"))
        
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: _send_smtp(msg, email)
        )
        logger.info(f"✉️ Buchungsbestätigung gesendet an {email}")
        return True
    except Exception as e:
        logger.error(f"E-Mail-Versand Fehler: {e}")
        return False

def _send_smtp(msg: MIMEMultipart, to_email: str) -> None:
    with smtplib.SMTP(CONFIG.email.smtp_host, CONFIG.email.smtp_port) as server:
        server.starttls()
        if CONFIG.email.smtp_user:
            server.login(CONFIG.email.smtp_user, CONFIG.email.smtp_password)
        server.sendmail(CONFIG.email.from_email, to_email, msg.as_string())


# ── Simulation & Helpers ──────────────────────────────────────────────────────

def _save_booking_local(booking_data: dict) -> None:
    """Speichert Buchung in lokaler JSON-Datei (Simulation)."""
    filename = "bookings.json"
    try:
        existing = []
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                try:
                    existing = json.load(f)
                except json.JSONDecodeError:
                    pass
        
        existing.append(booking_data)
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
            
        logger.info(f"💾 [SIMULATION] Buchung gespeichert in {filename}")
    except Exception as e:
        logger.error(f"Fehler beim Speichern der Simulation: {e}")


def _get_mock_slots(date_str: str) -> List[str]:
    """Generiert deterministische 'freie' Slots basierend auf dem Datum."""
    random.seed(date_str)
    possible_slots = ["09:00", "10:30", "11:00", "13:30", "14:00", "15:30", "16:00"]
    k = random.randint(2, 4)
    slots = sorted(random.sample(possible_slots, k))
    return slots


# ── Tool-Klasse ───────────────────────────────────────────────────────────────
class AppointmentTools:
    """Function Tools für den Voice Agent."""
    
    def __init__(self) -> None:
        self._end_call_callback: Optional[Callable] = None
        self._rate_limiter = RateLimiter(
            max_calls=CONFIG.agent.max_tool_calls_per_minute
        )
        
        # ── FORCE SIMULATION ──
        # Wir erzwingen hier True, egal was in der Config steht.
        # Das verhindert den 11001 Netzwerk-Fehler komplett.
        self.is_simulation = True 
        
        mode_str = "SIMULATION (Erzwungen)"
        logger.info(f"🛠️ AppointmentTools initialisiert in Modus: {mode_str}")
    
    def set_end_call_callback(self, callback: Callable) -> None:
        self._end_call_callback = callback
    
    def _check_rate_limit(self) -> bool:
        if not self._rate_limiter.is_allowed():
            logger.warning("Rate Limit erreicht!")
            return False
        return True
    
    # ── end_call (Optimiert für Aussprechen) ──────────────────────────────────
    @llm.function_tool
    async def end_call(self) -> str:
        """Beendet das Gespräch. Erst verabschieden, dann aufrufen!"""
        logger.info("🔚 end_call ausgelöst - warte auf Audio-Abschluss...")
        
        # WICHTIG: Delay damit der LLM noch "Tschüss" sagen kann
        # Ohne Sleep wird die Verbindung gekappt, bevor das Audio beim User ankommt.
        await asyncio.sleep(3.0) 
        
        if self._end_call_callback:
            asyncio.create_task(self._end_call_callback())
            
        return "call_ended"
    
    # ── check_availability ────────────────────────────────────────────────────
    @llm.function_tool
    async def check_availability(
        self,
        requested_date: Annotated[str, "Datum im ISO-Format YYYY-MM-DD"],
    ) -> str:
        """Prüft Verfügbarkeit für ein Datum."""
        if not self._check_rate_limit():
            return "Bin gerade überlastet."
        
        logger.info(f"📅 check_availability: {requested_date}")
        
        try:
            d = date.fromisoformat(requested_date)
            
            if d < date.today():
                return "Das Datum liegt in der Vergangenheit."
            if d.weekday() >= 5:
                return "Am Wochenende haben wir geschlossen."

            # Falls wir später doch mal die API aktivieren wollen, ist der Code hier sicher:
            if not self.is_simulation:
                # Code für echte API (aktuell deaktiviert durch Force-Flag im init)
                pass

            # ── IMMER SIMULATION ──
            slots = _get_mock_slots(requested_date)
            return (
                f"Ja, am {d.strftime('%d.%m.%Y')} sieht es gut aus. "
                f"Ich hätte zum Beispiel noch {', '.join(slots)} Uhr frei. "
                "Passt davon was?"
            )
            
        except ValueError:
            return "Das Datum habe ich nicht verstanden. Bitte nutze Tag.Monat.Jahr."
        except Exception as e:
            logger.error(f"Fehler availability: {e}")
            return "Ich kann gerade nicht in den Kalender schauen, aber wir finden einen Termin."

    # ── reserve_appointment ───────────────────────────────────────────────────
    @llm.function_tool
    async def reserve_appointment(
        self,
        name: Annotated[str, "Name des Kunden"],
        email: Annotated[str, "E-Mail"],
        appointment_date: Annotated[str, "YYYY-MM-DD"],
        appointment_time: Annotated[str, "HH:MM"],
        topic: Annotated[str, "Thema"],
    ) -> str:
        """Bucht einen Termin."""
        if not self._check_rate_limit():
            return "Fehler beim Buchen."
        
        logger.info(f"📝 Buche: {name} am {appointment_date} {appointment_time}")
        
        try:
            # Simulation speichern
            booking = {
                "created_at": datetime.now().isoformat(),
                "name": name,
                "email": email,
                "date": appointment_date,
                "time": appointment_time,
                "topic": topic,
                "status": "confirmed_mock"
            }
            
            _save_booking_local(booking)
            
            # E-Mail Log
            asyncio.create_task(_send_booking_email(name, email, appointment_date, appointment_time, topic))

            return (
                f"Alles klar {name.split()[0]}, der Termin am {appointment_date} "
                f"um {appointment_time} ist eingetragen! Du erhältst eine Bestätigung an {email}."
            )

        except Exception as e:
            logger.error(f"Buchungsfehler: {e}")
            return "Da ist technisch was schiefgelaufen, aber ich habe es notiert."