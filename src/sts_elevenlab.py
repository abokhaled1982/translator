import logging
import os
import asyncio
from dotenv import load_dotenv

from livekit import api
import livekit.agents as agents
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google, elevenlabs 

load_dotenv()
load_dotenv(".env.local")

logger = logging.getLogger("gemini-elevenlabs-hybrid")
logger.setLevel(logging.INFO)

class Assistant(Agent):
    def __init__(self):
        super().__init__(instructions="Du bist ein Dolmetscher.")

async def entrypoint(ctx: agents.JobContext):
    logger.info(f"Verbinde mit Raum: {ctx.room.name}")
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)

    # 1. GEHIRN: Gemini (Nur Text Modus)
    llm_model = google.beta.realtime.RealtimeModel(
        model="gemini-2.0-flash-exp",
        api_key=os.getenv("GOOGLE_API_KEY"),
        modalities=["text"], 
        instructions="""
            Du bist ein Dolmetscher.
            1. Höre den arabischen Input.
            2. Übersetze SOFORT ins Deutsche.
            3. Gib NUR den deutschen Text zurück.
        """,
    )

    # 2. MUND: ElevenLabs TTS (Korrigiert für deine Version)
    eleven_tts = elevenlabs.TTS(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        
        # KORREKTUR 1: 'model' statt 'model_id'
        model="eleven_turbo_v2_5", 
        
        # KORREKTUR 2: 'voice_id' (String) statt 'voice' (Objekt)
        voice_id="JBFqnCBsd6RMkjVDRZzb" # Das ist die ID für "George"
    )

    my_agent = Assistant()

    # 3. SESSION
    session = AgentSession(
        llm=llm_model,
        tts=eleven_tts
    )

    # --- CONSOLE PRINT ---
    @session.on("conversation_item_added")
    def on_item(event):
        item = getattr(event, 'item', event)
        text = ""
        if hasattr(item, 'content'):
            if isinstance(item.content, list):
                for part in item.content:
                    if hasattr(part, 'text'): text += part.text
            elif isinstance(item.content, str):
                text = item.content
        
        if text:
            if item.role == "user":
                print(f"\n🎤 GEHÖRT: {text}")
            elif item.role == "assistant":
                print(f"🤖 ÜBERSETZUNG (ElevenLabs): {text}")

    await session.start(my_agent, room=ctx.room)
    await session.generate_reply(instructions="Sag freundlich auf Deutsch: 'Ich bin bereit.'")

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))