import logging
import os
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv

# --- FIX FÜR DEN CIRCULAR IMPORT ---
# 1. Wir importieren 'api' ganz normal
from livekit import api

# 2. WICHTIG: Wir importieren 'agents' als Modul-Alias!
# Das verhindert, dass Python durcheinander kommt.
import livekit.agents as agents

# 3. Wir holen Agent und Session direkt aus dem Untermodul 'voice'
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google

load_dotenv()
load_dotenv(".env.local")

logger = logging.getLogger("gemini-stt-only")
logger.setLevel(logging.INFO)

def get_current_time_str():
    try:
        return datetime.now(timezone.utc).strftime("%H:%M")
    except Exception:
        return "Zeit unbekannt"

class Assistant(Agent):
    def __init__(self):
        super().__init__(instructions="Du bist ein Dolmetscher.")

# Beachte: Wir nutzen jetzt 'agents.JobContext' (durch den Alias oben)
async def entrypoint(ctx: agents.JobContext):
    logger.info(f"Verbinde mit Raum: {ctx.room.name}")
    
    # Wir nutzen 'agents.AutoSubscribe'
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)

    time_str = get_current_time_str()

    # --- GEMINI KONFIGURATION (STUMM / NUR TEXT) ---
    model = google.beta.realtime.RealtimeModel(
        model="gemini-2.0-flash-exp",
        api_key=os.getenv("GOOGLE_API_KEY"),
        voice="Puck",
        
        # Audio ausschalten -> Nur Text in Konsole
        modalities=["text"],
        
        instructions=f"""
            Du bist ein Dolmetscher. Es ist {time_str}.
            1. Höre den arabischen Input.
            2. Übersetze SOFORT ins Deutsche.
            3. Gib NUR Text aus. Generiere KEIN Audio.
        """,
    )

    my_agent = Assistant()
    session = AgentSession(llm=model)

    # Event Listener für die Konsole
    @session.on("conversation_item_added")
    def on_item(event):
        item = getattr(event, 'item', event)
        text = ""
        if hasattr(item, 'content'):
            if isinstance(item.content, list):
                for part in item.content:
                    if hasattr(part, 'text'): text += part.text
                    elif isinstance(part, str): text += part
            elif isinstance(item.content, str):
                text = item.content
        
        if text:
            role_icon = "🗣️ DU" if item.role == "user" else "🤖 GEMINI"
            print(f"\n{role_icon}: {text}")

    # Starten (Signatur: Agent zuerst, dann Raum benannt)
    await session.start(my_agent, room=ctx.room)
    
    # Initiale Nachricht (nur Text im Log)
    await session.generate_reply()

if __name__ == "__main__":
    # Wir nutzen den Alias 'agents.' für cli und WorkerOptions
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))