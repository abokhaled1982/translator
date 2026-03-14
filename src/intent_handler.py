"""
intent_handler.py — Shadow Tool Executor.

Monitors agent speech and executes Cal.com API calls without
Gemini Function Calling. Eliminates 1008 WebSocket errors completely.

Architecture:
  1. Gemini Live runs in pure audio mode (NO tools registered)
  2. System prompt instructs Gemini to say specific action phrases
  3. IntentHandler listens to conversation_item_added events
  4. When action phrase detected → execute API call in background
  5. Result injected via session.generate_reply()
"""
import asyncio
import re
import logging
from typing import Optional, Callable

from livekit.agents.voice import AgentSession

from tools import check_availability, reserve_appointment

logger = logging.getLogger("intraunit.intent")


# ── Regex Patterns ─────────────────────────────────────────────────────────────
# Agent: "Ich schaue kurz im Kalender nach fuer den 17.03.2026"
_RE_CHECK_AVAIL = re.compile(
    r"(?:schaue|schau|pr[uü]fe|check)"
    r".*?"
    r"(?:kalender|verf[uü]gbarkeit|termin)"
    r".*?"
    r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})",
    re.IGNORECASE | re.DOTALL,
)

# Fallback: ISO date in text "2026-03-17"
_RE_CHECK_AVAIL_ISO = re.compile(
    r"(?:schaue|schau|pr[uü]fe|check)"
    r".*?"
    r"(?:kalender|verf[uü]gbarkeit|termin)"
    r".*?"
    r"(\d{4})-(\d{2})-(\d{2})",
    re.IGNORECASE | re.DOTALL,
)

# Agent: "Ich trage den Termin ein fuer Max Müller, max@mail.de,
#         am 17.03.2026 um 14:00, Thema AI Beratung."
_RE_BOOK = re.compile(
    r"(?:trage|buche)"
    r".*?"
    r"(?:termin|ein)"
    r".*?"
    r"(?:f[uü]r|fuer)\s+(.+?),\s*"         # name
    r"([\w.\-+]+@[\w.\-]+\.\w+)"            # email (without trailing comma)
    r",?\s*"                                 # optional comma separator
    r"(?:am\s+)?(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})"  # date DD.MM.YYYY
    r"\s+(?:um\s+)?(\d{1,2}:\d{2})"         # time HH:MM
    r"(?:.*?[Tt]hema\s+(.+?))?[.!]?$",      # optional topic, optional punctuation
    re.IGNORECASE | re.DOTALL,
)

# End call: "Auf Wiedersehen" / "Tschüss"
_RE_END_CALL = re.compile(
    r"(?:auf\s*wiedersehen|tsch[uü]ss|tschuess|goodbye|bye\s*bye)",
    re.IGNORECASE,
)


class IntentHandler:
    """
    Shadow Tool Executor — monitors agent speech, executes tools in background.

    No Gemini Function Calling needed. No 1008 errors possible.
    """

    def __init__(
        self,
        session: AgentSession,
        end_callback: Optional[Callable] = None,
    ):
        self._session = session
        self._end_callback = end_callback
        self._processing = False
        self._closed = False

    def attach(self) -> None:
        """Register event listeners on the session."""
        self._session.on("conversation_item_added", self._on_item_added)
        logger.info("IntentHandler aktiv — Shadow Tool Executor laeuft")

    def _on_item_added(self, event) -> None:
        """Process new conversation items for action intents."""
        msg = event.item

        # Only process assistant messages
        if msg.role != "assistant":
            return

        text = msg.text_content
        if not text:
            return

        # Debounce: only one action at a time
        if self._processing:
            return

        # Check for intents and process async
        if _RE_CHECK_AVAIL.search(text) or _RE_CHECK_AVAIL_ISO.search(text):
            asyncio.create_task(self._handle_availability(text))
        elif _RE_BOOK.search(text):
            asyncio.create_task(self._handle_booking(text))
        elif _RE_END_CALL.search(text):
            asyncio.create_task(self._handle_end_call())

    # ── Intent Handlers ────────────────────────────────────────────────────────

    async def _handle_availability(self, text: str) -> None:
        """Extract date and check availability."""
        self._processing = True
        try:
            date_str = self._extract_date(text)
            if not date_str:
                logger.warning("Availability-Intent erkannt aber kein Datum extrahiert")
                await self._inject_result(
                    "Entschuldigung, ich konnte das Datum nicht erkennen. "
                    "Frage den Anrufer nochmal nach dem gewuenschten Datum."
                )
                return

            logger.info(f"Intent: check_availability({date_str})")
            result = await check_availability(date_str)
            await self._inject_result(result)

        except Exception as e:
            logger.error(f"check_availability Fehler: {e}", exc_info=True)
            await self._inject_result(
                "Entschuldigung, ich konnte gerade nicht auf den Kalender zugreifen. "
                "Frage den Anrufer ob du es gleich nochmal versuchen sollst."
            )
        finally:
            self._processing = False

    async def _handle_booking(self, text: str) -> None:
        """Extract booking data and reserve appointment."""
        self._processing = True
        try:
            m = _RE_BOOK.search(text)
            if not m:
                return

            name = m.group(1).strip()
            email = m.group(2).strip()
            day, month, year = m.group(3), m.group(4), m.group(5)
            time_str = m.group(6).strip()
            topic = (m.group(7) or "Beratungsgespraech").strip()

            year = self._normalize_year(year)
            date_str = f"{year}-{month.zfill(2)}-{day.zfill(2)}"

            logger.info(f"Intent: book({name}, {email}, {date_str} {time_str})")
            result = await reserve_appointment(
                name, email, date_str, time_str, topic
            )
            await self._inject_result(result)

        except Exception as e:
            logger.error(f"reserve_appointment Fehler: {e}", exc_info=True)
            await self._inject_result(
                "Entschuldigung, es gab ein technisches Problem bei der Buchung. "
                "Alle Daten wurden notiert. Herr Al-Ghobari meldet sich persoenlich."
            )
        finally:
            self._processing = False

    async def _handle_end_call(self) -> None:
        """Trigger end-call after goodbye audio plays."""
        logger.info("Intent: end_call")
        # Let goodbye audio finish playing
        await asyncio.sleep(3.5)
        if self._end_callback:
            asyncio.create_task(self._end_callback())

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _extract_date(self, text: str) -> Optional[str]:
        """Extract date from text, returns ISO format YYYY-MM-DD."""
        # Try DD.MM.YYYY first
        m = _RE_CHECK_AVAIL.search(text)
        if m:
            day, month, year = m.group(1), m.group(2), m.group(3)
            year = self._normalize_year(year)
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

        # Try YYYY-MM-DD
        m = _RE_CHECK_AVAIL_ISO.search(text)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

        return None

    @staticmethod
    def _normalize_year(year: str) -> str:
        """Normalize 2-digit year to 4-digit."""
        if len(year) == 2:
            return f"20{year}"
        return year

    def close(self) -> None:
        """Mark handler as closed — no more generate_reply calls."""
        self._closed = True
        logger.debug("IntentHandler geschlossen")

    async def _inject_result(self, text: str) -> None:
        """
        Inject tool result back into the conversation via generate_reply.
        
        Retries with backoff if Gemini is reconnecting after a 1008 drop.
        The LiveKit plugin auto-reconnects, we just need to wait.
        """
        if self._closed:
            logger.debug(f"inject_result ignoriert (Session geschlossen): {text[:80]}")
            return
        logger.info(f"Injecting result: {text[:100]}...")

        instructions = (
            f"Teile dem Anrufer folgendes MIT "
            f"(sage es natuerlich und freundlich, nicht woertlich ablesen): {text}"
        )

        max_retries = 3
        for attempt in range(max_retries):
            if self._closed:
                return
            try:
                if attempt > 0:
                    # Warten bis Gemini-Reconnect fertig ist
                    wait = 1.5 * attempt
                    logger.info(f"⏳ Warte {wait:.1f}s auf Gemini-Reconnect (Versuch {attempt + 1}/{max_retries})...")
                    await asyncio.sleep(wait)
                await self._session.generate_reply(instructions=instructions)
                return  # Erfolg
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"generate_reply Versuch {attempt + 1} fehlgeschlagen: {e}")
                else:
                    logger.error(f"generate_reply nach {max_retries} Versuchen fehlgeschlagen: {e}")
