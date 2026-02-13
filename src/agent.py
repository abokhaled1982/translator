"""
agent.py — SalesAssistant und Session-Lifecycle.

Trennung von Verantwortlichkeiten:
  - SalesAssistant: nur Persönlichkeit + Tools
  - build_session():  nur technische Konfiguration (Modell, VAD)
  - entrypoint():     nur LiveKit-Verbindung + Lifecycle
"""
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


def _attach_dev_console(session: AgentSession) -> None:
    """
    Gibt Konversation im Terminal aus — ausschließlich im DEV-Modus.
    In PROD: diese Funktion wird gar nicht aufgerufen.
    """
    @session.on("conversation_item_added")
    def _on_item(event) -> None:
        item = getattr(event, "item", event)
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

        if text:
            icon = "🗣️  DU" if item.role == "user" else "🤖 AGENT"
            print(f"\n{icon}: {text}", flush=True)


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

    await session.start(assistant, room=ctx.room)

    # Sofortige Begrüßung — kein Warten auf Kundeninitiative
    await session.generate_reply(instructions=CONFIG.agent.greeting)

    logger.info("Session aktiv, Agent bereit")
