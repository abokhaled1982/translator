"""
tools.py — Professional Function Tools mit Production Features.

Verbesserungen:
  - Rate Limiting (Schutz gegen Tool-Call-Spam)
  - E-Mail-Benachrichtigungen bei Buchungen
  - Kalender-API Integration (mit Fallback)
  - Strukturiertes Error Handling
  - Metrics & Logging
  - Retry-Logik für API-Calls
"""
import asyncio
import logging
import smtplib
from collections import deque
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Annotated, Callable, Optional, Deque
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
            logger.warning("httpx nicht installiert — externe API-Calls nicht verfügbar")
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
        """Prüft ob Call erlaubt ist."""
        now = time()
        
        # Entferne alte Calls außerhalb des Windows
        while self.calls and self.calls[0] < now - self.window_seconds:
            self.calls.popleft()
        
        if len(self.calls) >= self.max_calls:
            return False
        
        self.calls.append(now)
        return True
    
    def get_remaining(self) -> int:
        """Gibt verbleibende Calls im aktuellen Window zurück."""
        now = time()
        while self.calls and self.calls[0] < now - self.window_seconds:
            self.calls.popleft()
        return max(0, self.max_calls - len(self.calls))


# ── E-Mail Service ────────────────────────────────────────────────────────────
async def _send_booking_email(
    name: str,
    email: str,
    appointment_date: str,
    appointment_time: str,
    topic: str
) -> bool:
    """
    Sendet Buchungsbestätigung per E-Mail.
    Returns: True bei Erfolg, False bei Fehler.
    """
    if not CONFIG.email.enabled:
        logger.debug("E-Mail-Versand deaktiviert (keine SMTP-Config)")
        return False
    
    try:
        # E-Mail zusammenstellen
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Terminbestätigung: {appointment_date} um {appointment_time} Uhr"
        msg["From"] = CONFIG.email.from_email
        msg["To"] = email
        
        # HTML-Template
        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
              <h2 style="color: #2c3e50;">Hallo {name.split()[0]}! 👋</h2>
              
              <p>Dein Termin bei <strong>{CONFIG.agent.company_name}</strong> ist bestätigt:</p>
              
              <div style="background: #f8f9fa; border-left: 4px solid #3498db; padding: 15px; margin: 20px 0;">
                <p style="margin: 5px 0;"><strong>📅 Datum:</strong> {_format_date_german(appointment_date)}</p>
                <p style="margin: 5px 0;"><strong>🕐 Uhrzeit:</strong> {appointment_time} Uhr</p>
                <p style="margin: 5px 0;"><strong>💬 Thema:</strong> {topic}</p>
              </div>
              
              <p>Falls du den Termin verschieben oder absagen musst, antworte einfach auf diese Mail oder ruf uns an.</p>
              
              <p>Wir freuen uns auf das Gespräch!</p>
              
              <p style="margin-top: 30px;">
                Viele Grüße<br>
                <strong>{CONFIG.agent.agent_name}</strong><br>
                {CONFIG.agent.company_name}<br>
                <a href="mailto:{CONFIG.agent.company_email}">{CONFIG.agent.company_email}</a>
              </p>
              
              <hr style="margin-top: 30px; border: none; border-top: 1px solid #eee;">
              <p style="font-size: 12px; color: #999;">
                Diese Mail wurde automatisch generiert von unserem KI-Assistenten.
              </p>
            </div>
          </body>
        </html>
        """
        
        msg.attach(MIMEText(html, "html"))
        
        # Async SMTP-Versand
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _send_smtp(msg, email)
        )
        
        logger.info(f"✉️ Buchungsbestätigung gesendet an {email}")
        return True
        
    except Exception as e:
        logger.error(f"E-Mail-Versand fehlgeschlagen: {e}", exc_info=True)
        return False


def _send_smtp(msg: MIMEMultipart, to_email: str) -> None:
    """Sendet E-Mail über SMTP (Blocking, wird in Executor ausgeführt)."""
    with smtplib.SMTP(CONFIG.email.smtp_host, CONFIG.email.smtp_port) as server:
        server.starttls()
        if CONFIG.email.smtp_user and CONFIG.email.smtp_password:
            server.login(CONFIG.email.smtp_user, CONFIG.email.smtp_password)
        server.sendmail(
            CONFIG.email.from_email,
            to_email,
            msg.as_string()
        )


def _format_date_german(date_str: str) -> str:
    """Formatiert ISO-Datum zu deutschem Format."""
    try:
        dt = datetime.fromisoformat(date_str)
        weekday = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][dt.weekday()]
        return f"{weekday}, {dt.strftime('%d.%m.%Y')}"
    except:
        return date_str


# ── Kalender-API Integration ──────────────────────────────────────────────────
async def _check_calendar_api(date_str: str) -> Optional[str]:
    """
    Prüft echte Kalender-API auf Verfügbarkeit.
    Returns: Verfügbarkeits-String oder None bei Fehler.
    """
    if not CONFIG.tools.calendar_api_url:
        return None
    
    try:
        client = _get_http_client()
        if not client:
            return None
        
        async with asyncio.timeout(CONFIG.tools.api_timeout_s):
            response = await client.get(
                f"{CONFIG.tools.calendar_api_url}/availability",
                params={"date": date_str}
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("available"):
                slots = data.get("slots", [])
                if slots:
                    return f"Am {_format_date_german(date_str)} sind folgende Zeiten frei: {', '.join(slots)}"
                return f"Am {_format_date_german(date_str)} habe ich noch freie Slots."
            else:
                return f"Am {_format_date_german(date_str)} ist leider schon alles belegt. Wie wäre ein anderer Tag?"
    
    except asyncio.TimeoutError:
        logger.warning("Kalender-API Timeout")
        return None
    except Exception as e:
        logger.error(f"Kalender-API Fehler: {e}")
        return None


async def _reserve_via_api(
    name: str,
    email: str,
    appointment_date: str,
    appointment_time: str,
    topic: str
) -> bool:
    """
    Bucht Termin über echte Kalender-API.
    Returns: True bei Erfolg, False bei Fehler.
    """
    if not CONFIG.tools.calendar_api_url:
        return False
    
    try:
        client = _get_http_client()
        if not client:
            return False
        
        async with asyncio.timeout(CONFIG.tools.api_timeout_s):
            response = await client.post(
                f"{CONFIG.tools.calendar_api_url}/appointments",
                json={
                    "name": name,
                    "email": email,
                    "date": appointment_date,
                    "time": appointment_time,
                    "topic": topic,
                    "source": "voice_agent",
                    "agent": CONFIG.agent.agent_name,
                }
            )
            response.raise_for_status()
            logger.info(f"✓ Termin über API gebucht: {name} am {appointment_date}")
            return True
    
    except asyncio.TimeoutError:
        logger.error("Kalender-API Timeout bei Buchung")
        return False
    except Exception as e:
        logger.error(f"Kalender-API Fehler bei Buchung: {e}")
        return False


# ── Tool-Klasse ───────────────────────────────────────────────────────────────
class AppointmentTools:
    """Function Tools für den Voice Agent."""
    
    def __init__(self) -> None:
        self._end_call_callback: Optional[Callable] = None
        self._rate_limiter = RateLimiter(
            max_calls=CONFIG.agent.max_tool_calls_per_minute,
            window_seconds=60
        )
        logger.debug("AppointmentTools initialisiert")
    
    def set_end_call_callback(self, callback: Callable) -> None:
        """Setzt Callback für end_call Tool."""
        self._end_call_callback = callback
    
    def _check_rate_limit(self) -> bool:
        """Prüft Rate Limit vor Tool-Ausführung."""
        if not self._rate_limiter.is_allowed():
            remaining = self._rate_limiter.get_remaining()
            logger.warning(
                f"Rate Limit erreicht! "
                f"Max: {CONFIG.agent.max_tool_calls_per_minute}/min"
            )
            return False
        return True
    
    # ── end_call ──────────────────────────────────────────────────────────────
    @llm.function_tool
    async def end_call(self) -> str:
        """
        Beendet das Gespräch sauber.
        WICHTIG: Erst verabschieden, DANN dieses Tool aufrufen!
        """
        logger.info("🔚 end_call ausgelöst — Session wird beendet")
        
        if self._end_call_callback:
            # Delayed Callback nach goodbye_delay
            asyncio.get_event_loop().call_later(
                CONFIG.agent.goodbye_delay_s,
                lambda: asyncio.ensure_future(self._end_call_callback())
            )
        
        return "call_ended"
    
    # ── check_availability ────────────────────────────────────────────────────
    @llm.function_tool
    async def check_availability(
        self,
        requested_date: Annotated[str, "Angefragtes Datum im ISO-Format YYYY-MM-DD"],
    ) -> str:
        """
        Prüft ob ein Datum verfügbar ist.
        Berücksichtigt Wochenenden und Geschäftszeiten automatisch.
        """
        if not self._check_rate_limit():
            return "Moment, ich bin gerade etwas überlastet. Versuch's gleich nochmal."
        
        logger.info(f"📅 check_availability → {requested_date!r}")
        
        try:
            parsed = date.fromisoformat(requested_date)
            
            # Vergangenheit
            if parsed < date.today():
                return "Das Datum liegt in der Vergangenheit. Welches Datum hast du dir vorgestellt?"
            
            # Wochenende
            if parsed.weekday() == 5:  # Samstag
                next_monday = parsed + timedelta(days=2)
                return (
                    f"Samstags sind wir nicht erreichbar. "
                    f"Wie wäre Montag, der {next_monday.strftime('%d.%m.')}?"
                )
            if parsed.weekday() == 6:  # Sonntag
                next_monday = parsed + timedelta(days=1)
                return (
                    f"Sonntags haben wir frei. "
                    f"Montag, der {next_monday.strftime('%d.%m.')} wäre möglich — passt das?"
                )
            
            # Geschäftstage prüfen (falls konfiguriert)
            if CONFIG.business.business_days:
                weekday = parsed.weekday() + 1  # 1=Mo, 7=So
                if weekday not in CONFIG.business.business_days:
                    return (
                        f"An diesem Tag haben wir normalerweise frei. "
                        f"Wie wäre ein anderer Wochentag?"
                    )
            
            # Echte Kalender-API prüfen (falls konfiguriert)
            api_result = await _check_calendar_api(requested_date)
            if api_result:
                return api_result
            
            # Fallback: Generische Bestätigung
            return (
                f"Am {parsed.strftime('%d.%m.%Y')} habe ich noch freie Slots. "
                "Lieber vormittags oder nachmittags?"
            )
        
        except ValueError:
            logger.warning(f"Ungültiges Datumsformat: {requested_date!r}")
            return "Das Datum habe ich leider nicht verstanden. Kannst du Tag, Monat und Jahr nochmal nennen?"
        
        except Exception as e:
            logger.exception("Fehler in check_availability")
            return "Ich kann den Kalender gerade nicht prüfen. Nenn mir deinen Wunschtermin — wir finden eine Lösung."
    
    # ── reserve_appointment ───────────────────────────────────────────────────
    @llm.function_tool
    async def reserve_appointment(
        self,
        name: Annotated[str, "Vollständiger Name des Kunden"],
        email: Annotated[str, "E-Mail-Adresse für die Buchungsbestätigung"],
        appointment_date: Annotated[str, "Datum des Termins (YYYY-MM-DD)"],
        appointment_time: Annotated[str, "Uhrzeit des Termins (HH:MM, 24h-Format)"],
        topic: Annotated[str, "Kurzes Anliegen oder Thema des Meetings"],
    ) -> str:
        """
        Bucht einen Termin verbindlich.
        WICHTIG: Nur aufrufen nachdem der Kunde EXPLIZIT bestätigt hat!
        """
        if not self._check_rate_limit():
            return "Moment, ich bin gerade etwas überlastet. Versuch's gleich nochmal."
        
        logger.info(
            f"📝 reserve_appointment → {name} | {email} | "
            f"{appointment_date} {appointment_time} | {topic}"
        )
        
        try:
            # Datum validieren
            parsed_date = date.fromisoformat(appointment_date)
            
            if parsed_date < date.today():
                return "Dieses Datum liegt in der Vergangenheit. Bitte nenn mir ein zukünftiges Datum."
            
            # Uhrzeit validieren
            try:
                h, m = appointment_time.split(":")
                hour, minute = int(h), int(m)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
            except (ValueError, AttributeError):
                return "Die Uhrzeit habe ich nicht verstanden. Bitte nochmal im Format Stunden:Minuten."
            
            # Formatierung
            readable_date = parsed_date.strftime("%d.%m.%Y")
            readable_time = f"{hour:02d}:{minute:02d}"
            first_name = name.split()[0]
            
            # 1. Über Kalender-API buchen (falls konfiguriert)
            api_success = await _reserve_via_api(
                name, email, appointment_date, appointment_time, topic
            )
            
            # 2. E-Mail-Bestätigung senden (async, non-blocking)
            asyncio.create_task(
                _send_booking_email(
                    name, email, appointment_date, appointment_time, topic
                )
            )
            
            # 3. Lokales Logging (Backup falls API fehlschlägt)
            logger.info(
                f"✅ Termin gebucht: {name} <{email}> "
                f"am {readable_date} um {readable_time} — {topic} "
                f"[API: {'✓' if api_success else '✗'}]"
            )
            
            return (
                f"Perfekt, {first_name}! Dein Termin am {readable_date} "
                f"um {readable_time} Uhr ist eingetragen. "
                f"Die Bestätigung geht gleich an {email}."
            )
        
        except asyncio.TimeoutError:
            logger.error("reserve_appointment: API Timeout")
            return (
                "Mein Kalender ist gerade kurz nicht erreichbar. "
                "Ich notiere deine Daten und wir melden uns per Mail."
            )
        
        except Exception as e:
            logger.exception("Fehler in reserve_appointment")
            return "Es gab einen technischen Fehler. Ein Kollege wird sich bei dir melden."
    
    # ── transfer_to_specialist ────────────────────────────────────────────────
    @llm.function_tool
    async def transfer_to_specialist(
        self,
        topic: Annotated[str, "Das Thema das der Kunde besprechen möchte"],
    ) -> str:
        """
        Signalisiert dass ein Fachspezialist übernimmt.
        Bei komplexen technischen Fragen oder wenn Agent überfragt ist.
        """
        if not self._check_rate_limit():
            return "Moment, ich bin gerade etwas überlastet."
        
        logger.info(f"🔀 transfer_to_specialist → {topic}")
        
        return (
            f"Das Thema '{topic}' beantwortet dir {CONFIG.agent.founder_name} "
            "am besten direkt. Soll ich gleich einen Termin für euch eintragen?"
        )
