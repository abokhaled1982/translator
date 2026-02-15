"""
agent.py — Professional Agent Logic mit Production Features.

Verbesserungen:
  - Natürlicher Gesprächsfluss mit realistischen Pausen
  - Robustes Session-Management mit Reconnect-Logik
  - Graceful Degradation bei Fehlern
  - Strukturiertes Error Handling
  - Health Check Integration
  - Metrics & Monitoring Ready
"""
import asyncio
import logging
from typing import Optional

from livekit.agents import JobContext, AutoSubscribe
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google

import health
from config import CONFIG
from tools import AppointmentTools

logger = logging.getLogger("intraunit.agent")


# ── Agent ─────────────────────────────────────────────────────────────────────
class SalesAssistant(Agent, AppointmentTools):
    """Professioneller Voice Sales Agent mit natürlichem Gesprächsverhalten."""
    
    def __init__(self) -> None:
        Agent.__init__(self, instructions=CONFIG.agent.system_prompt)
        AppointmentTools.__init__(self)
        logger.debug(f"✨ {CONFIG.agent.agent_name} initialisiert")


# ── Model & Session Builder ───────────────────────────────────────────────────
def _build_model() -> google.realtime.RealtimeModel:
    """
    Baut das Gemini Realtime Model.
    WICHTIG: max_output_tokens wird NICHT übergeben —
    die Gemini Live API unterstützt diesen Parameter nicht (führt zu 1008).
    """
    return google.realtime.RealtimeModel(
        model=CONFIG.voice.model,
        api_key=CONFIG.google_api_key,
        voice=CONFIG.voice.voice,
        temperature=CONFIG.voice.temperature,
    )


def _build_session() -> AgentSession:
    """
    Session ohne lokales VAD — Audio direkt gestreamt, maximale Performance.
    Gemini macht Audio nativ (kein separates TTS nötig).
    """
    return AgentSession(
        llm=_build_model(),
        tts=None,  # Gemini macht Audio nativ
    )


# ── Retry-Wrapper für Session-Start ──────────────────────────────────────────
async def _start_session_with_retry(
    session: AgentSession,
    assistant: SalesAssistant,
    room,
) -> None:
    """
    Startet Session mit Exponential Backoff bei Fehlern.
    
    Raises:
        RuntimeError: Nach allen Versuchen fehlgeschlagen
    """
    cfg = CONFIG.session
    last_error: Optional[Exception] = None
    
    for attempt in range(cfg.max_retries):
        try:
            await session.start(assistant, room=room)
            logger.info(
                f"✓ Session gestartet (Versuch {attempt + 1}/{cfg.max_retries})"
            )
            return
        
        except Exception as e:
            last_error = e
            wait = cfg.backoff_base_s ** attempt
            
            logger.warning(
                f"⚠️  Session-Start Versuch {attempt + 1}/{cfg.max_retries} "
                f"fehlgeschlagen: {type(e).__name__}: {e}",
                exc_info=(attempt == cfg.max_retries - 1)  # Stack trace beim letzten Versuch
            )
            
            if attempt < cfg.max_retries - 1:
                logger.info(f"🔄 Retry in {wait:.1f}s...")
                await asyncio.sleep(wait)
    
    raise RuntimeError(
        f"Session konnte nach {cfg.max_retries} Versuchen nicht gestartet werden: "
        f"{type(last_error).__name__}: {last_error}"
    )


# ── Session Reconnect Logic ──────────────────────────────────────────────────
async def _handle_reconnect(
    session: AgentSession,
    assistant: SalesAssistant,
    room,
    end_event: asyncio.Event
) -> bool:
    """
    Versucht Session nach Disconnect wiederherzustellen.
    
    Returns:
        True bei Erfolg, False wenn aufgegeben werden soll
    """
    if not CONFIG.session.enable_reconnect:
        logger.info("Session Reconnect deaktiviert")
        return False
    
    logger.warning("🔌 Session disconnected — versuche Reconnect...")
    health.mark_not_ready()
    
    for attempt in range(CONFIG.session.max_reconnect_attempts):
        try:
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
            
            logger.info(f"🔄 Reconnect-Versuch {attempt + 1}...")
            await session.start(assistant, room=room)
            
            logger.info("✓ Session erfolgreich wiederhergestellt")
            health.mark_ready()
            
            # Kurze Info an User
            await session.generate_reply(
                instructions=(
                    "Die Verbindung war kurz unterbrochen, aber jetzt läuft alles wieder. "
                    "Wo waren wir stehen geblieben?"
                )
            )
            
            return True
        
        except Exception as e:
            logger.warning(
                f"⚠️  Reconnect-Versuch {attempt + 1} fehlgeschlagen: {e}"
            )
    
    logger.error("❌ Reconnect fehlgeschlagen — beende Session")
    end_event.set()
    return False


# ── Natürliche Greeting-Logik ────────────────────────────────────────────────
async def _send_greeting(
    session: AgentSession,
    end_event: asyncio.Event
) -> None:
    """
    Sendet natürliche Begrüßung mit realistischer Verzögerung.
    """
    # Kurze Pause vor Begrüßung (natürlicher als sofort)
    await asyncio.sleep(CONFIG.agent.greeting_delay_s)
    
    if not end_event.is_set():
        try:
            await session.generate_reply(instructions=CONFIG.agent.greeting)
            logger.debug("👋 Greeting gesendet")
        except RuntimeError as e:
            logger.warning(f"Greeting nicht gesendet: {e}")


# ── Natürliche Goodbye-Logik ─────────────────────────────────────────────────
async def _send_goodbye(
    session: AgentSession,
    reason: str = "timeout"
) -> None:
    """
    Sendet natürliche Verabschiedung abhängig vom Grund.
    """
    try:
        if reason == "timeout":
            message = (
                "Die maximale Gesprächsdauer ist leider erreicht. "
                "Lass uns gerne beim nächsten Mal weitermachen. Ciao!"
            )
        elif reason == "error":
            message = (
                "Entschuldige, da gibt's gerade ein technisches Problem. "
                "Wir melden uns bei dir. Bis dann!"
            )
        else:
            message = "Alles klar, mach's gut!"
        
        await session.generate_reply(instructions=message)
        logger.debug(f"👋 Goodbye gesendet (Grund: {reason})")
        
        # Kurze Pause damit Goodbye noch gesendet wird
        await asyncio.sleep(CONFIG.agent.goodbye_delay_s)
    
    except Exception as e:
        logger.warning(f"Goodbye nicht gesendet: {e}")


# ── Main Entrypoint ───────────────────────────────────────────────────────────
async def entrypoint(ctx: JobContext) -> None:
    """
    Haupt-Entrypoint für jeden Voice-Call.
    Managed kompletten Session-Lifecycle mit Graceful Error Handling.
    """
    room_name = ctx.room.name
    logger.info(f"🚀 Session Start: {room_name}")
    
    # Room verbinden
    try:
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    except Exception as e:
        logger.error(f"❌ Room-Connect fehlgeschlagen: {e}", exc_info=True)
        health.mark_unhealthy()
        return
    
    # Agent & Session initialisieren
    assistant = SalesAssistant()
    session = _build_session()
    
    # Event für Gesprächsende (end_call Tool, User-Disconnect, Timeout)
    end_event = asyncio.Event()
    
    # ── end_call Callback ─────────────────────────────────────────────────────
    # In agent.py suchen wir die Funktion entrypoint und ändern den _handle_end_call

    # ── end_call Callback ─────────────────────────────────────────────────────
    async def _handle_end_call() -> None:
        """Wird vom end_call Tool ausgelöst — beendet Session sauber."""
        logger.info(f"📞 Agent möchte auflegen. Warte auf Audio-Output...")
        
        # WICHTIG: Wir warten 4 Sekunden bei offener Leitung.
        # Das garantiert, dass die Verabschiedung ("Tschüss!") beim User ankommt,
        # bevor wir den WebSocket killen.
        await asyncio.sleep(4.0)
        
        logger.info(f"📞 Call jetzt wirklich beendet: {room_name}")
        health.mark_not_ready()
        end_event.set()
    
    assistant.set_end_call_callback(_handle_end_call)
    
    # ── Session starten mit Retry ─────────────────────────────────────────────
    try:
        await _start_session_with_retry(session, assistant, ctx.room)
    except RuntimeError as e:
        logger.critical(f"❌ Session-Start fehlgeschlagen: {e}")
        health.mark_not_ready()
        return
    
    # Session läuft — als ready markieren (Kubernetes Readiness Probe)
    health.mark_ready()
    logger.info(f"✓ Agent ready: {room_name}")
    
    # ── Disconnect-Event Handler ──────────────────────────────────────────────
    @ctx.room.on("disconnected")
    def _on_disconnect(*_):
        logger.info(f"🔌 User disconnected: {room_name}")
        end_event.set()
    
    # ── Greeting senden ───────────────────────────────────────────────────────
    await _send_greeting(session, end_event)
    
    # ── Main Wait Loop ────────────────────────────────────────────────────────
    # Warten bis Call beendet wird durch:
    #   - end_call Tool (Agent beendet)
    #   - User-Disconnect
    #   - Max-Call-Duration Timeout
    
    try:
        await asyncio.wait_for(
            end_event.wait(),
            timeout=CONFIG.agent.max_call_duration_s,
        )
        logger.info(f"✓ Call regulär beendet: {room_name}")
    
    except asyncio.TimeoutError:
        logger.warning(
            f"⏱️  Max-Call-Dauer ({CONFIG.agent.max_call_duration_s}s) erreicht: "
            f"{room_name}"
        )
        await _send_goodbye(session, reason="timeout")
    
    except Exception as e:
        logger.error(f"❌ Fehler während Session: {e}", exc_info=True)
        await _send_goodbye(session, reason="error")
    
    finally:
        # ── Cleanup ───────────────────────────────────────────────────────────
        health.mark_not_ready()
        logger.info(f"🛑 Session beendet: {room_name}")
        
        try:
            await session.aclose()
        except Exception as e:
            logger.debug(f"Session-Close Fehler (ignoriert): {e}")
