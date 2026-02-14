"""
agent.py — Agent Logic.
SilenceHandler entfernt — Stille-Erkennung laeuft nativ ueber
Gemini turn_detection (server_vad). Das LLM handelt Schweigen
selbst gemaess System-Prompt.
"""
import asyncio
import logging

from livekit.agents import JobContext, AutoSubscribe
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google

from config import CONFIG
from tools import AppointmentTools

logger = logging.getLogger("intraunit.agent")


# ── Agent ─────────────────────────────────────────────────────────────────────
class SalesAssistant(Agent, AppointmentTools):
    def __init__(self) -> None:
        Agent.__init__(self, instructions=CONFIG.agent.system_prompt)
        logger.debug("SalesAssistant initialisiert")


# ── Model & Session Builder ───────────────────────────────────────────────────
def _build_model() -> google.realtime.RealtimeModel:
    return google.realtime.RealtimeModel(
        model=CONFIG.voice.model,
        api_key=CONFIG.google_api_key,
        voice=CONFIG.voice.voice,
        temperature=CONFIG.voice.temperature,
        # Gemini Live API hat VAD-basierte Turn-Detection bereits eingebaut.
        # Kein extra Parameter noetig — laeuft automatisch.
    )


def _build_session() -> AgentSession:
    """Session OHNE lokales VAD — Audio direkt gestreamt, maximale Performance."""
    return AgentSession(
        llm=_build_model(),
        tts=None,  # Gemini macht Audio nativ
    )


# ── Retry-Wrapper fuer Session-Start ─────────────────────────────────────────
async def _start_session_with_retry(
    session: AgentSession,
    assistant: SalesAssistant,
    room,
) -> None:
    """Exponential backoff beim Session-Start — verhindert Crash bei kurzer Nichterreichbarkeit."""
    cfg = CONFIG.retry
    last_error: Exception | None = None

    for attempt in range(cfg.max_attempts):
        try:
            await session.start(assistant, room=room)
            logger.info(f"Session gestartet (Versuch {attempt + 1})")
            return
        except Exception as e:
            last_error = e
            wait = cfg.backoff_base_s ** attempt
            logger.warning(
                f"Session-Start Versuch {attempt + 1}/{cfg.max_attempts} "
                f"fehlgeschlagen ({e}), retry in {wait:.1f}s..."
            )
            if attempt < cfg.max_attempts - 1:
                await asyncio.sleep(wait)

    raise RuntimeError(
        f"Session konnte nach {cfg.max_attempts} Versuchen nicht gestartet werden: {last_error}"
    )


# ── Entrypoint ────────────────────────────────────────────────────────────────
async def entrypoint(ctx: JobContext) -> None:
    logger.info(f"Session Start: {ctx.room.name}")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    assistant = SalesAssistant()
    session = _build_session()

    try:
        await _start_session_with_retry(session, assistant, ctx.room)
    except RuntimeError as e:
        logger.critical(str(e))
        return

    # Disconnect-Event VOR dem Greeting registrieren —
    # verhindert Race-Condition wenn User sofort auflegt
    disconnect_event = asyncio.Event()

    @ctx.room.on("disconnected")
    def _on_disconnect(*_):
        disconnect_event.set()

    # Greeting nur senden wenn Session noch laeuft
    await asyncio.sleep(CONFIG.agent.greeting_delay_s)
    if not disconnect_event.is_set():
        try:
            await session.generate_reply(instructions=CONFIG.agent.greeting)
        except RuntimeError as e:
            logger.warning(f"Greeting nicht gesendet (Session bereits beendet): {e}")

    try:
        await disconnect_event.wait()
    finally:
        logger.info(f"Session beendet: {ctx.room.name}")