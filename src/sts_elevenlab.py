import logging
import os
import asyncio
from dotenv import load_dotenv

from livekit import api
import livekit.agents as agents
from livekit.agents.voice import Agent, AgentSession
# Wir brauchen Silero für die Präzision (VAD)
from livekit.plugins import google, elevenlabs, silero

load_dotenv()
load_dotenv(".env.local")

logger = logging.getLogger("gemini-translator-strict")
logger.setLevel(logging.INFO)

class Assistant(Agent):
    def __init__(self):
        super().__init__(instructions="Du bist ein Dolmetscher.")

async def entrypoint(ctx: agents.JobContext):
    logger.info(f"Verbinde mit Raum: {ctx.room.name}")
    
    # WICHTIG: Echo Cancellation auf dem Client (Frontend) ist wichtig!
    # Aber hier aktivieren wir Audio.
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)

    # 1. GEHIRN: Gemini (Streng konfigurierter Prompt)
    llm_model = google.beta.realtime.RealtimeModel(
        model="gemini-2.0-flash-exp",
        api_key=os.getenv("GOOGLE_API_KEY"),
        modalities=["text"], # Nur Text zurück, damit ElevenLabs spricht
        instructions="""
            SYSTEM INSTRUKTION:
            Du bist KEIN Chatbot. Du bist eine reine Übersetzungs-API.
            
            DEINE REGELN:
            1. Input: Arabische Sprache (vom Nutzer).
            2. Output: Deutsche Übersetzung (Text).
            3. Verhalten:
               - Übersetze SOFORT und PRÄZISE.
               - Füge KEINE Einleitungen hinzu (wie "Hier ist die Übersetzung").
               - Wenn der Input unverständlich ist oder nur Rauschen: Gib LEEREN Text zurück.
               - WIEDERHOLE NIEMALS den arabischen Input.
               - WIEDERHOLE NIEMALS deine eigene vorherige Übersetzung.
               - Wenn der Input Deutsch ist, ignoriere ihn (um Echos zu vermeiden).
        """,
    )

    # 2. MUND: ElevenLabs
    eleven_tts = elevenlabs.TTS(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        model="eleven_turbo_v2_5", 
        voice_id="JBFqnCBsd6RMkjVDRZzb" # George
    )

    my_agent = Assistant()

    # 3. SESSION: Mit VAD (Voice Activity Detection)
    # Das VAD hilft, Pausen zu erkennen und verhindert, dass Rauschen übersetzt wird.
    session = AgentSession(
        llm=llm_model,
        tts=eleven_tts,
        vad=silero.VAD.load() # <-- WICHTIG: Filtert Atemgeräusche und Rauschen weg
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
                print(f"\n🎤 INPUT: {text}")
            elif item.role == "assistant":
                print(f"🇩🇪 OUTPUT: {text}")

    await session.start(my_agent, room=ctx.room)
    
    # Keine Begrüßung mehr, um Wiederholungen beim Start zu vermeiden.
    # Der Agent wartet still auf Input.

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))