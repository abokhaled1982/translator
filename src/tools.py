"""
tools.py — Alle Function-Tools des Intraunit-Agenten.

Verbesserungen:
  - context: RunContext entfernt (nie benutzt, konnte 1008 ausloesen)
  - end_call Tool — beendet Session sauber nach Aufgaben-Abschluss
  - reserve_appointment: email-Feld hinzugefuegt fuer Buchungsbestaetigung
  - HTTP Connection-Pool als Singleton
"""
import asyncio
import logging
from datetime import date, timedelta
from typing import Annotated, Callable, Optional

from livekit.agents import llm

from config import CONFIG

logger = logging.getLogger("intraunit.tools")


# ── HTTP Connection-Pool ──────────────────────────────────────────────────────
_http_client = None


def _get_http_client():
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
                headers={"User-Agent": "IntraUnit-Agent/1.0"},
            )
        except ImportError:
            logger.warning("httpx nicht installiert")
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


# ── Tool-Klasse ───────────────────────────────────────────────────────────────
class AppointmentTools:

    def __init__(self) -> None:
        self._end_call_callback: Optional[Callable] = None

    def set_end_call_callback(self, callback: Callable) -> None:
        self._end_call_callback = callback

    # ── end_call ──────────────────────────────────────────────────────────────
    @llm.function_tool
    async def end_call(self) -> str:
        """
        Beendet das Gespraech sauber.
        Aufrufen nachdem die Verabschiedung gesagt wurde.
        """
        logger.info("end_call ausgeloest")
        if self._end_call_callback:
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
        """Prueft ob ein Datum verfuegbar ist. Wochenenden werden automatisch erkannt."""
        logger.info(f"check_availability → {requested_date!r}")
        try:
            parsed = date.fromisoformat(requested_date)

            if parsed < date.today():
                return "Das Datum liegt in der Vergangenheit. Welches Datum hast du dir vorgestellt?"

            if parsed.weekday() == 5:
                next_monday = parsed + timedelta(days=2)
                return (
                    f"Samstags sind wir nicht erreichbar. "
                    f"Wie waere Montag, der {next_monday.strftime('%d.%m.%Y')}?"
                )
            if parsed.weekday() == 6:
                next_monday = parsed + timedelta(days=1)
                return (
                    f"Sonntags haben wir frei. "
                    f"Montag, der {next_monday.strftime('%d.%m.%Y')} waere moeglich — passt das?"
                )

            # TODO: Echte Kalender-API einbinden
            return (
                f"Am {parsed.strftime('%d.%m.%Y')} habe ich noch freie Slots. "
                "Lieber Vormittags oder Nachmittags?"
            )

        except ValueError:
            logger.warning(f"Ungueltiges Datumsformat: {requested_date!r}")
            return "Das Datum habe ich leider nicht verstanden. Kannst du Tag, Monat und Jahr nochmal nennen?"
        except Exception:
            logger.exception("Fehler in check_availability")
            return "Ich kann den Kalender gerade nicht pruefen. Nenn mir deinen Wunschtermin — wir finden eine Loesung."

    # ── reserve_appointment ───────────────────────────────────────────────────
    @llm.function_tool
    async def reserve_appointment(
        self,
        name: Annotated[str, "Vollstaendiger Name des Kunden"],
        email: Annotated[str, "E-Mail-Adresse fuer die Buchungsbestaetigung"],
        appointment_date: Annotated[str, "Datum des Termins (YYYY-MM-DD)"],
        appointment_time: Annotated[str, "Uhrzeit des Termins (HH:MM, 24h-Format)"],
        topic: Annotated[str, "Kurzes Anliegen oder Thema des Meetings"],
    ) -> str:
        """
        Bucht einen Termin verbindlich.
        Nur aufrufen nachdem der Kunde ausdruecklich bestaetigt hat.
        """
        logger.info(f"reserve_appointment → {name} | {email} | {appointment_date} {appointment_time} | {topic}")
        try:
            parsed_date = date.fromisoformat(appointment_date)

            if parsed_date < date.today():
                return "Dieses Datum liegt in der Vergangenheit. Bitte nenn mir ein zukuenftiges Datum."

            try:
                h, m = appointment_time.split(":")
                hour, minute = int(h), int(m)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
            except (ValueError, AttributeError):
                return "Die Uhrzeit habe ich nicht verstanden. Bitte nochmal im Format Stunden:Minuten."

            readable_date = parsed_date.strftime("%d.%m.%Y")
            readable_time = f"{hour:02d}:{minute:02d}"

            # TODO: Echte Kalender-API / CRM einbinden:
            # async with asyncio.timeout(CONFIG.tools.api_timeout_s):
            #     client = _get_http_client()
            #     resp = await client.post("/appointments", json={
            #         "name": name,
            #         "email": email,
            #         "date": appointment_date,
            #         "time": appointment_time,
            #         "topic": topic,
            #     })

            logger.info(f"Termin gebucht: {name} <{email}> am {readable_date} um {readable_time} — {topic}")
            return (
                f"Alles klar, {name.split()[0]} — dein Termin am {readable_date} um {readable_time} Uhr ist eingetragen. "
                f"Die Bestaetigung geht an {email}."
            )

        except asyncio.TimeoutError:
            logger.error("reserve_appointment: API Timeout")
            return "Mein Kalender ist gerade kurz nicht erreichbar. Ich notiere deine Daten und Waled meldet sich per Mail."
        except Exception:
            logger.exception("Fehler in reserve_appointment")
            return "Es gab einen technischen Fehler. Ein Kollege wird sich bei dir melden."

    # ── transfer_to_specialist ────────────────────────────────────────────────
    @llm.function_tool
    async def transfer_to_specialist(
        self,
        topic: Annotated[str, "Das Thema das der Kunde besprechen moechte"],
    ) -> str:
        """Signalisiert dass Waled persoenlich uebernimmt. Bei komplexen technischen Fragen."""
        logger.info(f"transfer_to_specialist → {topic}")
        return (
            f"Das Thema '{topic}' beantwortet dir Waled am besten direkt. "
            "Soll ich gleich einen Termin fuer euch eintragen?"
        )
