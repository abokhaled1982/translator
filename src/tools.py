"""
tools.py — Alle Function-Tools des Intraunit-Agenten.

Jede Funktion:
  1. Kündigt die Aktion dem Nutzer an (sofort, vor dem API-Call)
  2. Führt die Aktion aus (async, non-blocking)
  3. Gibt eine klare Bestätigung oder Fehlermeldung zurück

Erweiterung: Echte Kalender-API unter den # TODO-Kommentaren einbauen.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Annotated

from livekit.agents import llm, RunContext

logger = logging.getLogger("intraunit.tools")


class AppointmentTools:
    """
    Gebündelte Tool-Klasse für den SalesAssistant.
    Alle Methoden sind @llm.function_tool-dekoriert und werden
    automatisch vom LLM aufgerufen.
    """

    @llm.function_tool
    async def check_availability(
        self,
        context: RunContext,
        requested_date: Annotated[str, "Angefragtes Datum im ISO-Format YYYY-MM-DD"],
    ) -> str:
        """
        Prüft, ob ein Datum verfügbar ist.
        Erkennt Wochenenden und schlägt automatisch den nächsten Werktag vor.
        """
        logger.info(f"check_availability → {requested_date}")

        try:
            parsed = datetime.strptime(requested_date, "%Y-%m-%d").date()

            if parsed < date.today():
                return (
                    "Dieses Datum liegt in der Vergangenheit. "
                    "Welches zukünftige Datum passt Ihnen?"
                )

            # Wochenende → nächsten Montag vorschlagen
            if parsed.weekday() == 5:  # Samstag
                next_monday = parsed + timedelta(days=2)
                return (
                    f"Samstags sind wir nicht erreichbar. "
                    f"Ich hätte noch freie Slots am Montag, dem {next_monday.strftime('%d.%m.%Y')} — passt das?"
                )
            if parsed.weekday() == 6:  # Sonntag
                next_monday = parsed + timedelta(days=1)
                return (
                    f"Sonntags haben wir Ruhetag. "
                    f"Wie wäre Montag, der {next_monday.strftime('%d.%m.%Y')}?"
                )

            # TODO: Echte Kalender-API einbinden
            # slots = await calendar_api.get_slots(parsed)
            # if not slots: return "An diesem Tag bin ich leider ausgebucht ..."

            return (
                f"Am {parsed.strftime('%d.%m.%Y')} habe ich noch freie Slots. "
                "Lieber Vormittags oder Nachmittags?"
            )

        except ValueError:
            logger.warning(f"Ungültiges Datumsformat: {requested_date!r}")
            return "Das Datum konnte ich nicht lesen. Bitte nennen Sie mir Tag, Monat und Jahr."
        except Exception:
            logger.exception("Fehler in check_availability")
            return (
                "Ich kann den Kalender gerade nicht einsehen. "
                "Nennen Sie mir Ihren Wunschtermin — wir finden eine Lösung."
            )

    @llm.function_tool
    async def reserve_appointment(
        self,
        context: RunContext,
        name: Annotated[str, "Vollständiger Name des Kunden"],
        appointment_date: Annotated[str, "Datum des Termins (YYYY-MM-DD)"],
        appointment_time: Annotated[str, "Uhrzeit des Termins (HH:MM)"],
    ) -> str:
        """
        Bucht einen Termin verbindlich.
        Wird erst aufgerufen, nachdem der Kunde ausdrücklich zugestimmt hat.
        """
        logger.info(f"reserve_appointment → {name} | {appointment_date} {appointment_time}")

        try:
            parsed_date = datetime.strptime(appointment_date, "%Y-%m-%d").date()

            if parsed_date < date.today():
                return (
                    "Dieses Datum liegt in der Vergangenheit. "
                    "Bitte nennen Sie mir ein zukünftiges Datum."
                )

            parsed_time = datetime.strptime(appointment_time, "%H:%M").time()
            readable_date = parsed_date.strftime("%d.%m.%Y")
            readable_time = parsed_time.strftime("%H:%M")

            # TODO: Echten API-Call einbauen, z.B.:
            # result = await calendar_api.post("/appointments", json={
            #     "name": name, "date": appointment_date, "time": appointment_time
            # })
            # if not result.ok: raise ConnectionError(result.text)

            logger.info(f"Termin erfolgreich gebucht: {name} am {readable_date} um {readable_time}")
            return (
                f"Perfekt, {name} — Ihr Termin am {readable_date} um {readable_time} Uhr "
                "ist jetzt fest eingetragen. Sie erhalten gleich eine Bestätigung per E-Mail."
            )

        except ValueError as e:
            logger.warning(f"Format-Fehler bei Buchung: {e}")
            return (
                "Datum oder Uhrzeit konnte ich nicht lesen. "
                "Bitte nennen Sie mir Tag, Monat, Jahr und die Uhrzeit noch einmal."
            )
        except ConnectionError as e:
            logger.error(f"Kalender nicht erreichbar: {e}")
            return (
                "Mein Kalender ist gerade kurz nicht erreichbar. "
                "Ich notiere Ihre Daten und ein Kollege bestätigt den Termin per Rückruf."
            )
        except Exception:
            logger.exception("Unerwarteter Fehler in reserve_appointment")
            return (
                "Es gab einen technischen Fehler. "
                "Ein Mitarbeiter ruft Sie zur Bestätigung zurück."
            )

    @llm.function_tool
    async def transfer_to_specialist(
        self,
        context: RunContext,
        topic: Annotated[str, "Das technische Thema, das der Kunde besprechen möchte"],
    ) -> str:
        """
        Signalisiert dem Kunden, dass ein Spezialist übernimmt.
        Wird bei komplexen technischen Fragen eingesetzt.
        """
        logger.info(f"transfer_to_specialist → Thema: {topic}")

        # TODO: Hier tatsächlichen Transfer-Mechanismus einbauen (z.B. LiveKit SIP Transfer)
        return (
            f"Das Thema '{topic}' klärt unser Spezialist direkt mit Ihnen — "
            "das ist genau der richtige Ansprechpartner dafür. "
            "Soll ich gleich einen Termin mit ihm für Sie reservieren?"
        )
