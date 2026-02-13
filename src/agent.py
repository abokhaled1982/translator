"""
agent.py — SalesAssistant und Session-Lifecycle.

Trennung von Verantwortlichkeiten:
  - SalesAssistant:   nur Persönlichkeit + Tools
  - SilenceHandler:   Erkennt Stille / unverständliche Antworten,
                      wiederholt letzte Frage — Werte aus CONFIG.silence
  - _build_session(): nur technische Konfiguration (Modell, VAD)
  - entrypoint():     nur LiveKit-Verbindung + Lifecycle
"""
import asyncio
import logging

from livekit.agents import JobContext, AutoSubscribe
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google, silero

from config import CONFIG
from tools import AppointmentTools

logger = logging.getLogger("intraunit.agent")


class SalesAssistant(Agent, AppointmentTools):
    """
    Intraunit Vertriebs-Assistent.
    Erbt Agent (LiveKit) + AppointmentTools (Function-Tools).
    Durch Mehrfachvererbung werden alle @llm.function_tool-Methoden
    automatisch vom LLM erkannt — keine manuelle Registrierung nötig.
    """

    def __init__(self) -> None:
        Agent.__init__(self, instructions=CONFIG.agent.system_prompt)
        logger.debug("SalesAssistant initialisiert")


# ── Silence-Handler ───────────────────────────────────────────────────────────

class SilenceHandler:
    """
    Überwacht die Session auf Nutzerstille oder unverständliche Eingaben.

    Logik:
      1. Nach jeder Agenten-Antwort startet ein Timer (CONFIG.silence.timeout_s).
      2. Spricht der Nutzer innerhalb des Timeouts → Timer wird zurückgesetzt.
      3. Läuft der Timer ab → Agent wiederholt die letzte Frage
         (max. CONFIG.silence.max_repeats mal).
      4. Nach max_repeats Wiederholungen → höfliche Verabschiedung.

    Alle Zeitwerte kommen aus CONFIG.silence — keine hardcodierten Konstanten.
    """

    def __init__(self, session: AgentSession) -> None:
        self._session = session
        self._cfg = CONFIG.silence
        self._last_agent_text: str = ""
        self._repeat_count: int = 0
        self._timer_task: asyncio.Task | None = None

    # ── Öffentliche Steuerung ──────────────────────────────────────────────

    def attach(self) -> None:
        """Registriert alle benötigten Event-Listener an der Session."""

        @self._session.on("conversation_item_added")
        def _on_item(event) -> None:
            item = getattr(event, "item", event)
            role = getattr(item, "role", None)
            text = _extract_text(item)

            if role == "assistant" and text:
                # Neue Agenten-Antwort → letzte Frage merken, Timer starten
                self._last_agent_text = text
                self._repeat_count = 0
                self._restart_timer()
                logger.debug("SilenceHandler: Agent-Text gespeichert, Timer gestartet")

            elif role == "user" and text:
                # Nutzer hat gesprochen → Timer stoppen
                self._cancel_timer()
                logger.debug("SilenceHandler: Nutzereingabe erkannt, Timer gestoppt")

    # ── Interne Timer-Logik ────────────────────────────────────────────────

    def _restart_timer(self) -> None:
        self._cancel_timer()
        self._timer_task = asyncio.ensure_future(self._silence_timer())

    def _cancel_timer(self) -> None:
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None

    async def _silence_timer(self) -> None:
        try:
            await asyncio.sleep(self._cfg.timeout_s)
        except asyncio.CancelledError:
            return  # Nutzer hat gesprochen → alles gut

        if self._repeat_count < self._cfg.max_repeats:
            await self._repeat_last_question()
        else:
            await self._close_session_politely()

    async def _repeat_last_question(self) -> None:
        """Wiederholt die letzte Agentenfrage mit natürlicher Einleitung."""
        self._repeat_count += 1
        await asyncio.sleep(self._cfg.repeat_delay_s)

        phrase = _build_repeat_phrase(self._repeat_count)
        instruction = (
            f"{phrase} Wiederhole deine letzte Frage sinngemäß kurz: "
            f'"{self._last_agent_text}"'
        )

        logger.info(
            f"SilenceHandler: Wiederholung {self._repeat_count}/{self._cfg.max_repeats}"
        )
        await self._session.generate_reply(instructions=instruction)

    async def _close_session_politely(self) -> None:
        """Beendet das Gespräch höflich nach zu vielen Versuchen."""
        logger.info("SilenceHandler: Maximale Wiederholungen erreicht, Verabschiedung")
        await asyncio.sleep(self._cfg.repeat_delay_s)
        await self._session.generate_reply(
            instructions=(
                "Der Kunde hat mehrfach nicht geantwortet. "
                "Verabschiede dich kurz und freundlich und beende das Gespräch."
            )
        )


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _extract_text(item) -> str:
    """Extrahiert lesbaren Text aus einem Conversation-Item."""
    text = ""
    if hasattr(item, "content"):
        if isinstance(item.content, list):
            for part in item.content:
                if hasattr(part, "text"):
                    text += part.text
                elif isinstance(part, str):
                    text += part
        elif isinstance(item.content, str):
            text = item.content
    return text.strip()


def _build_repeat_phrase(repeat_count: int) -> str:
    """Natürlich klingende Einleitungen — kein roboterhafter Eindruck."""
    phrases = {
        1: "Ich habe Sie vielleicht nicht richtig gehört.",
        2: "Entschuldigung, ich glaube die Verbindung ist etwas schwierig.",
    }
    return phrases.get(repeat_count, "Ich frage noch einmal kurz nach.")


# ── Modell / VAD / Session ────────────────────────────────────────────────────

def _build_model() -> google.realtime.RealtimeModel:
    """Erstellt das Gemini Realtime-Modell mit optimierten Parametern."""
    return google.realtime.RealtimeModel(
        model=CONFIG.voice.model,
        api_key=CONFIG.google_api_key,
        voice=CONFIG.voice.voice,
        temperature=CONFIG.voice.temperature,
    )


def _build_vad() -> silero.VAD:
    """
    Erstellt den Voice Activity Detector.
    Niedrige Schwellwerte = minimale Latenz zwischen Sprechen und Antwort.
    """
    return silero.VAD.load(
        min_silence_duration=CONFIG.vad.min_silence_duration,
        min_speech_duration=CONFIG.vad.min_speech_duration,
    )


def _build_session() -> AgentSession:
    """Erstellt eine fertig konfigurierte AgentSession."""
    return AgentSession(
        llm=_build_model(),
        vad=_build_vad(),
    )


# ── Dev-Konsole ───────────────────────────────────────────────────────────────

def _attach_dev_console(session: AgentSession) -> None:
    """
    Gibt Konversation im Terminal aus — ausschließlich im DEV-Modus.
    In PROD: diese Funktion wird gar nicht aufgerufen.
    """
    @session.on("conversation_item_added")
    def _on_item(event) -> None:
        item = getattr(event, "item", event)
        text = _extract_text(item)
        if text:
            icon = "🗣️  DU" if item.role == "user" else "🤖 AGENT"
            print(f"\n{icon}: {text}", flush=True)


# ── Entrypoint ────────────────────────────────────────────────────────────────

async def entrypoint(ctx: JobContext) -> None:
    """
    LiveKit Job-Entrypoint.
    Verbindet mit dem Room, baut Session auf, startet den Agenten.
    """
    logger.info(f"Session startet in Room: {ctx.room.name!r}")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    assistant = SalesAssistant()
    session = _build_session()

    # Konsolenausgabe nur im DEV-Modus
    if CONFIG.mode == "DEV":
        _attach_dev_console(session)

    # Stille-Erkennung aktivieren — wiederholt letzte Frage bei Nutzerschweigen
    silence_handler = SilenceHandler(session)
    silence_handler.attach()

    await session.start(assistant, room=ctx.room)

    # Sofortige Begrüßung — kein Warten auf Kundeninitiative
    await session.generate_reply(instructions=CONFIG.agent.greeting)

    logger.info("Session aktiv, Agent bereit")
