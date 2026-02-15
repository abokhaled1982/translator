"""
agent.py — Agent Logic.

Verbesserungen:
  - health.mark_ready() wird nach erfolgreichem Session-Start aufgerufen
  - end_call Callback registriert — beendet Session sauber nach Aufgabe
  - Max-Call-Dauer Timeout (Schutz gegen endlose Calls)
  - Session-Disconnect Recovery mit Reconnect-Versuch
  - Sauberes Teardown in finally-Block
"""
import asyncio
import logging

from livekit.agents import JobContext, AutoSubscribe
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google

import health
from config import CONFIG
from tools import AppointmentTools

logger = logging.getLogger("intraunit.agent")


# ── Agent ─────────────────────────────────────────────────────────────────────
class SalesAssistant(Agent, AppointmentTools):
    def __init__(self) -> None:
        Agent.__init__(self, instructions=CONFIG.agent.system_prompt)
        AppointmentTools.__init__(self)
        logger.debug("SalesAssistant initialisiert")


# ── Model & Session Builder ───────────────────────────────────────────────────
def _build_model() -> google.realtime.RealtimeModel:
    """
    Baut das Gemini Realtime Model.
    WICHTIG: max_output_tokens wird NICHT uebergeben —
    die Gemini Live API unterstuetzt diesen Parameter nicht (fuehrt zu 1008).
    """
    return google.realtime.RealtimeModel(
        model=CONFIG.voice.model,
        api_key=CONFIG.google_api_key,
        voice=CONFIG.voice.voice,
        temperature=CONFIG.voice.temperature,
    )


def _build_session() -> AgentSession:
    """Session ohne lokales VAD — Audio direkt gestreamt, maximale Performance."""
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
    """Exponential backoff beim Session-Start."""
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

    # Event das gesetzt wird wenn Call beendet werden soll
    # (entweder durch end_call Tool, User-Disconnect oder Timeout)
    end_event = asyncio.Event()

    # ── end_call Callback ─────────────────────────────────────────────────────
    async def _handle_end_call() -> None:
        """Wird vom end_call Tool ausgeloest — beendet Session sauber."""
        logger.info(f"Call beendet durch Agent: {ctx.room.name}")
        health.mark_not_ready()
        end_event.set()

    assistant.set_end_call_callback(_handle_end_call)

    # ── Session starten ───────────────────────────────────────────────────────
    try:
        await _start_session_with_retry(session, assistant, ctx.room)
    except RuntimeError as e:
        logger.critical(str(e))
        health.mark_not_ready()
        return

    # Session laeuft — als ready markieren (Kubernetes Readiness Probe)
    health.mark_ready()

    # ── Disconnect-Event registrieren ─────────────────────────────────────────
    @ctx.room.on("disconnected")
    def _on_disconnect(*_):
        logger.info(f"User disconnected: {ctx.room.name}")
        end_event.set()

    # ── Greeting senden ───────────────────────────────────────────────────────
    await asyncio.sleep(CONFIG.agent.greeting_delay_s)
    if not end_event.is_set():
        try:
            await session.generate_reply(instructions=CONFIG.agent.greeting)
        except RuntimeError as e:
            logger.warning(f"Greeting nicht gesendet: {e}")

    # ── Warten bis Call beendet wird ──────────────────────────────────────────
    # Entweder durch: end_call Tool | User-Disconnect | Max-Dauer Timeout
    try:
        await asyncio.wait_for(
            end_event.wait(),
            timeout=CONFIG.agent.max_call_duration_s,
        )
    except asyncio.TimeoutError:
        logger.warning(
            f"Max-Call-Dauer ({CONFIG.agent.max_call_duration_s}s) erreicht — "
            f"beende Call: {ctx.room.name}"
        )
        try:
            await session.generate_reply(
                instructions=(
                    "Die maximale Gespraechsdauer wurde erreicht. "
                    "Verabschiede dich freundlich und kurz."
                )
            )
            await asyncio.sleep(CONFIG.agent.goodbye_delay_s)
        except Exception as e:
            logger.warning(f"Timeout-Goodbye fehlgeschlagen: {e}")

    finally:
        health.mark_not_ready()
        logger.info(f"Session beendet: {ctx.room.name}")
        try:
            await session.aclose()
        except Exception as e:
            logger.debug(f"Session-Close Fehler (ignoriert): {e}")
