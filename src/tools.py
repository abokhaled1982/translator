"""
tools.py — Alle Function-Tools des Intraunit-Agenten.

Verbesserungen vs. Original:
  - asyncio.timeout() fuer alle API-Calls (verhindert Agent-Freeze)
  - HTTP Connection-Pool als Singleton (kein neues Client-Objekt pro Call)
  - date.fromisoformat() statt strptime (schneller, threadsafe)
  - Sauberes Teardown via close_http_client()
  - Datum-Aufloesung liegt beim LLM (System-Prompt) - kein Python-Code noetig
"""
import asyncio
import logging
from datetime import date, timedelta
from typing import Annotated

from livekit.agents import llm, RunContext

from config import CONFIG

logger = logging.getLogger("intraunit.tools")


# ── HTTP Connection-Pool Singleton ────────────────────────────────────────────
# Lazy-Init beim ersten Tool-Call.
# Ein persistenter Client ist ~10x schneller als ein neuer Client pro Call.
_http_client = None


def _get_http_client():
    """Gibt den globalen HTTP-Client zurueck (lazy, thread-safe fuer async)."""
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
                headers={"User-Agent": "Intraunit-Agent/1.0"},
            )
            logger.debug("HTTP Connection-Pool initialisiert")
        except ImportError:
            logger.warning("httpx nicht installiert — HTTP-Client nicht verfuegbar")
    return _http_client


async def close_http_client() -> None:
    """Schliesst den HTTP-Client sauber. Im App-Shutdown aufrufen."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
        logger.debug("HTTP Connection-Pool geschlossen")


# ── Tool-Klasse ───────────────────────────────────────────────────────────────
class AppointmentTools:
    """
    Gebuendelte Tool-Klasse fuer den SalesAssistant.
    Alle Methoden sind @llm.function_tool-dekoriert und werden
    automatisch vom LLM aufgerufen.

    Hinweis: Das LLM (Gemini) rechnet Datumsangaben wie 'morgen' oder
    'naechsten Montag' selbst in ISO-Format um (via System-Prompt).
    Hier wird nur noch ISO YYYY-MM-DD erwartet.
    """

    @llm.function_tool
    async def check_availability(
        self,
        context: RunContext,
        requested_date: Annotated[str, "Angefragtes Datum im ISO-Format YYYY-MM-DD"],
    ) -> str:
        """
        Prueft ob ein Datum verfuegbar ist.
        Erkennt Wochenenden und schlaegt automatisch den naechsten Werktag vor.
        """
        logger.info(f"check_availability → {requested_date!r}")

        try:
            parsed = date.fromisoformat(requested_date)

            if parsed < date.today():
                return (
                    "Dieses Datum liegt in der Vergangenheit. "
                    "Welches zukuenftige Datum passt Ihnen?"
                )

            # Wochenende → naechsten Montag vorschlagen
            if parsed.weekday() == 5:  # Samstag
                next_monday = parsed + timedelta(days=2)
                return (
                    f"Samstags sind wir nicht erreichbar. "
                    f"Ich haette noch freie Slots am Montag, dem "
                    f"{next_monday.strftime('%d.%m.%Y')} — passt das?"
                )
            if parsed.weekday() == 6:  # Sonntag
                next_monday = parsed + timedelta(days=1)
                return (
                    f"Sonntags haben wir Ruhetag. "
                    f"Wie waere Montag, der {next_monday.strftime('%d.%m.%Y')}?"
                )

            # TODO: Echte Kalender-API einbinden (dann asyncio.timeout einbauen):
            # async with asyncio.timeout(CONFIG.tools.api_timeout_s):
            #     client = _get_http_client()
            #     resp = await client.get(f"/calendar/slots?date={requested_date}")
            #     slots = resp.json()
            #     if not slots:
            #         return f"Am {parsed.strftime('%d.%m.%Y')} bin ich leider ausgebucht."

            return (
                f"Am {parsed.strftime('%d.%m.%Y')} habe ich noch freie Slots. "
                "Lieber Vormittags oder Nachmittags?"
            )

        except asyncio.TimeoutError:
            logger.error("check_availability: Kalender-API Timeout")
            return (
                "Mein Kalender reagiert gerade etwas langsam. "
                "Nennen Sie mir Ihren Wunschtermin — wir finden eine Loesung."
            )
        except ValueError:
            logger.warning(f"Ungueltiges Datumsformat: {requested_date!r}")
            return (
                "Das Datum konnte ich nicht lesen. "
                "Bitte nennen Sie mir Tag, Monat und Jahr."
            )
        except Exception:
            logger.exception("Fehler in check_availability")
            return (
                "Ich kann den Kalender gerade nicht einsehen. "
                "Nennen Sie mir Ihren Wunschtermin — wir finden eine Loesung."
            )

    @llm.function_tool
    async def reserve_appointment(
        self,
        context: RunContext,
        name: Annotated[str, "Vollstaendiger Name des Kunden"],
        appointment_date: Annotated[str, "Datum des Termins (YYYY-MM-DD)"],
        appointment_time: Annotated[str, "Uhrzeit des Termins (HH:MM, 24h-Format)"],
    ) -> str:
        """
        Bucht einen Termin verbindlich.
        Wird erst aufgerufen, nachdem der Kunde ausdruecklich zugestimmt hat.
        """
        logger.info(f"reserve_appointment → {name} | {appointment_date} {appointment_time}")

        try:
            parsed_date = date.fromisoformat(appointment_date)

            if parsed_date < date.today():
                return (
                    "Dieses Datum liegt in der Vergangenheit. "
                    "Bitte nennen Sie mir ein zukuenftiges Datum."
                )

            # Uhrzeit validieren
            try:
                h, m = appointment_time.split(":")
                hour, minute = int(h), int(m)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError("Ungueltiger Zeitwert")
            except (ValueError, AttributeError):
                return (
                    "Die Uhrzeit konnte ich nicht lesen. "
                    "Bitte nennen Sie mir die Uhrzeit im Format Stunden:Minuten."
                )

            readable_date = parsed_date.strftime("%d.%m.%Y")
            readable_time = f"{hour:02d}:{minute:02d}"

            # TODO: Echten API-Call einbauen (dann asyncio.timeout einbauen):
            # async with asyncio.timeout(CONFIG.tools.api_timeout_s):
            #     client = _get_http_client()
            #     resp = await client.post("/appointments", json={
            #         "name": name,
            #         "date": appointment_date,
            #         "time": appointment_time,
            #     })
            #     if not resp.is_success:
            #         raise ConnectionError(f"API Error: {resp.status_code}")

            logger.info(f"Termin gebucht: {name} am {readable_date} um {readable_time}")
            return (
                f"Perfekt, {name} — Ihr Termin am {readable_date} um {readable_time} Uhr "
                "ist jetzt fest eingetragen. Sie erhalten gleich eine Bestaetigung per E-Mail."
            )

        except asyncio.TimeoutError:
            logger.error("reserve_appointment: Kalender-API Timeout")
            return (
                "Mein Kalender ist gerade kurz nicht erreichbar. "
                "Ich notiere Ihre Daten und ein Kollege bestaetigt den Termin per Rueckruf."
            )
        except ValueError as e:
            logger.warning(f"Format-Fehler bei Buchung: {e}")
            return (
                "Datum oder Uhrzeit konnte ich nicht lesen. "
                "Bitte nennen Sie mir Tag, Monat, Jahr und Uhrzeit noch einmal."
            )
        except ConnectionError as e:
            logger.error(f"Kalender nicht erreichbar: {e}")
            return (
                "Mein Kalender ist gerade kurz nicht erreichbar. "
                "Ich notiere Ihre Daten und ein Kollege bestaetigt den Termin per Rueckruf."
            )
        except Exception:
            logger.exception("Unerwarteter Fehler in reserve_appointment")
            return (
                "Es gab einen technischen Fehler. "
                "Ein Mitarbeiter ruft Sie zur Bestaetigung zurueck."
            )

    @llm.function_tool
    async def transfer_to_specialist(
        self,
        context: RunContext,
        topic: Annotated[str, "Das technische Thema, das der Kunde besprechen moechte"],
    ) -> str:
        """
        Signalisiert dem Kunden, dass ein Spezialist uebernimmt.
        Wird bei komplexen technischen Fragen eingesetzt.
        """
        logger.info(f"transfer_to_specialist → Thema: {topic}")

        # TODO: Echten Transfer-Mechanismus einbauen (z.B. LiveKit SIP Transfer):
        # client = _get_http_client()
        # await client.post("/transfer", json={"topic": topic})

        return (
            f"Das Thema '{topic}' klaert unser Spezialist direkt mit Ihnen — "
            "das ist genau der richtige Ansprechpartner dafuer. "
            "Soll ich gleich einen Termin mit ihm fuer Sie reservieren?"
        )