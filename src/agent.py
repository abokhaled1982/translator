"""
agent.py — High-Performance Agent Logic.
Optimierungen:
  - Kein lokales VAD (Silero entfernt).
  - Keine blockierenden Calls.
"""
import asyncio
import logging

from livekit.agents import JobContext, AutoSubscribe
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google

from config import CONFIG
from tools import AppointmentTools

logger = logging.getLogger("intraunit.agent")

class SalesAssistant(Agent, AppointmentTools):
    def __init__(self) -> None:
        Agent.__init__(self, instructions=CONFIG.agent.system_prompt)
        logger.debug("SalesAssistant initialisiert")

# ── Silence-Handler ───────────────────────────────────────────────────────────
class SilenceHandler:
    def __init__(self, session: AgentSession) -> None:
        self._session = session
        self._cfg = CONFIG.silence
        self._last_agent_text: str = ""
        self._repeat_count: int = 0
        self._timer_task: asyncio.Task | None = None

    def attach(self) -> None:
        @self._session.on("conversation_item_added")
        def _on_item(event) -> None:
            item = getattr(event, "item", event)
            role = getattr(item, "role", None)
            text = _extract_text(item)

            if role == "assistant" and text:
                self._last_agent_text = text
                self._repeat_count = 0
                self._restart_timer()
            elif role == "user" and text:
                self._cancel_timer()

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
            return

        if self._repeat_count < self._cfg.max_repeats:
            await self._repeat_last_question()
        else:
            await self._close_session_politely()

    async def _repeat_last_question(self) -> None:
        self._repeat_count += 1
        logger.info(f"SilenceHandler: Wiederholung {self._repeat_count}")
        # Kurze Pause für Natürlichkeit
        await asyncio.sleep(0.5) 
        
        instruction = (
            f"Der Nutzer hat nicht geantwortet. Frage höflich nach. "
            f"Wiederhole sinngemäß: '{self._last_agent_text}'"
        )
        await self._session.generate_reply(instructions=instruction)

    async def _close_session_politely(self) -> None:
        logger.info("SilenceHandler: Timeout.")
        await self._session.generate_reply(
            instructions="Verabschiede dich kurz wegen Inaktivität."
        )

# ── Helper ────────────────────────────────────────────────────────────────────
def _extract_text(item) -> str:
    text = ""
    if hasattr(item, "content"):
        if isinstance(item.content, str):
            text = item.content
        elif isinstance(item.content, list):
            for part in item.content:
                if hasattr(part, "text"): text += part.text
                elif isinstance(part, str): text += part
    return text.strip()

# ── Setup (OHNE VAD) ──────────────────────────────────────────────────────────
def _build_model() -> google.realtime.RealtimeModel:
    return google.realtime.RealtimeModel(
        model=CONFIG.voice.model,
        api_key=CONFIG.google_api_key,
        voice=CONFIG.voice.voice,
        # WICHTIG: modalities entfernt, da dies Fehler 1007 verursacht
        temperature=CONFIG.voice.temperature,
    )

def _build_session() -> AgentSession:
    """
    Erstellt Session OHNE VAD.
    Das Audio wird direkt gestreamt. Maximale Performance.
    """
    return AgentSession(
        llm=_build_model(),      
        tts=None,  # Gemini macht Audio nativ
    )

# ── Entrypoint ────────────────────────────────────────────────────────────────
async def entrypoint(ctx: JobContext) -> None:
    logger.info(f"Session Start: {ctx.room.name}")
    
    # Audio Only abonnieren spart Bandbreite
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    assistant = SalesAssistant()
    session = _build_session()

    # Silence Handler als Hintergrund-Logik
    silence_handler = SilenceHandler(session)
    silence_handler.attach()

    await session.start(assistant, room=ctx.room)
    
    # Initialer Ping an Gemini für die Begrüßung
    await session.generate_reply(instructions=CONFIG.agent.greeting)