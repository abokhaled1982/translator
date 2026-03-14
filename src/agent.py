"""
agent.py — Voice Agent mit Shadow Tool Executor.

Kein Gemini Function Calling — eliminiert 1008 WebSocket-Fehler komplett.
Tools werden vom IntentHandler im Hintergrund ausgeführt.
"""
import asyncio
import logging
import threading
from typing import Optional

from livekit.agents import JobContext, AutoSubscribe
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google

import health
from config import CONFIG
from intent_handler import IntentHandler

logger = logging.getLogger("intraunit.agent")


# ── Agent ─────────────────────────────────────────────────────────────────────
class SalesAssistant(Agent):
    """Voice Sales Agent — reiner Audio-Modus ohne Function Calling."""
    
    def __init__(self) -> None:
        super().__init__(instructions=CONFIG.agent.system_prompt)
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
                    "Die Verbindung war kurz unterbrochen, aber jetzt ist alles wieder in Ordnung. "
                    "Entschuldigen Sie die Störung — wo waren wir stehen geblieben?"
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
                "Vielen Dank für Ihren Anruf — melden Sie sich gerne jederzeit wieder. Auf Wiedersehen!"
            )
        elif reason == "error":
            message = (
                "Entschuldigen Sie, es gibt gerade ein technisches Problem. "
                "Herr Al-Ghobari meldet sich persönlich bei Ihnen. Auf Wiedersehen!"
            )
        else:
            message = "Vielen Dank für Ihren Anruf. Auf Wiedersehen!"
        
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

    # Suppress "ignoring text stream" warnings — drain in a separate thread
    # so the main asyncio loop (LLM) is never blocked or slowed down.
    _stream_drain_loop = asyncio.new_event_loop()

    def _drain_thread():
        asyncio.set_event_loop(_stream_drain_loop)
        _stream_drain_loop.run_forever()

    _drain_t = threading.Thread(target=_drain_thread, daemon=True, name="stream-drain")
    _drain_t.start()

    async def _drain_reader(reader):
        try:
            async for _ in reader:
                pass
        except Exception:
            pass

    def _offload_stream(reader, _participant_identity):
        asyncio.run_coroutine_threadsafe(_drain_reader(reader), _stream_drain_loop)

    ctx.room.register_text_stream_handler("lk.agent.request", _offload_stream)
    
    # ── SIP-Anrufer erkennen ──────────────────────────────────────────────────
    caller_number = None
    is_sip_call = False
    for p in ctx.room.remote_participants.values():
        if p.kind == "SIP" or (p.attributes and p.attributes.get("sip.callID")):
            is_sip_call = True
            caller_number = (p.attributes or {}).get("sip.phoneNumber", "unbekannt")
            logger.info(f"📞 SIP-Anruf von: {caller_number}")
            break
    
    if not is_sip_call and room_name.startswith("call-"):
        is_sip_call = True
        logger.info("📞 SIP-Anruf erkannt (Room-Prefix)")
    
    if is_sip_call:
        logger.info(f"☎️  Telefonanruf aktiv — Raum: {room_name}")
    
    # Agent & Session initialisieren
    assistant = SalesAssistant()
    session = _build_session()
    
    # Event für Gesprächsende (IntentHandler end_call, User-Disconnect, Timeout)
    end_event = asyncio.Event()
    
    # ── end_call Callback ─────────────────────────────────────────────────────

    # ── end_call Callback ─────────────────────────────────────────────────────
    async def _handle_end_call() -> None:
        """Wird vom IntentHandler bei Verabschiedung ausgelöst."""
        logger.info(f"📞 Verabschiedung erkannt. Beende Call: {room_name}")
        health.mark_not_ready()
        end_event.set()
    
    # ── IntentHandler (Shadow Tool Executor) ──────────────────────────────────
    intent_handler = IntentHandler(
        session=session,
        end_callback=_handle_end_call,
    )
    
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
    
    # IntentHandler an laufende Session anhängen
    intent_handler.attach()
    
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
        intent_handler.close()  # Stop injecting into closed session
        _stream_drain_loop.call_soon_threadsafe(_stream_drain_loop.stop)
        logger.info(f"🛑 Session beendet: {room_name}")
        
        try:
            await session.aclose()
        except Exception as e:
            logger.debug(f"Session-Close Fehler (ignoriert): {e}")
