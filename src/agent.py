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
# from google.genai import types # Brauchen wir jetzt nicht mehr

load_dotenv()
load_dotenv(".env")

logger = logging.getLogger("gemini-agent")
logger.setLevel(logging.INFO)

def get_current_time_str():
    try:
        return datetime.now(timezone.utc).strftime("%H:%M Uhr (UTC)")
    except Exception:
        return "Unbekannte Zeit"

class Assistant(Agent):
    def __init__(self):
        super().__init__(instructions="Du bist ein hilfreicher Assistent.")

# FEHLER 1 BEHOBEN: Hier muss 'agents.JobContext' stehen
async def entrypoint(ctx: agents.JobContext):
    logger.info(f"Verbinde mit Raum: {ctx.room.name}")
    
    # FEHLER 2 BEHOBEN: Hier muss 'agents.AutoSubscribe' stehen
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)

    time_str = get_current_time_str()

    # --- GEMINI KONFIGURATION ---
    # Fix: thinking_config wurde entfernt!
    model = google.beta.realtime.RealtimeModel(
        model="gemini-2.0-flash-exp",
        api_key=os.getenv("GOOGLE_API_KEY"),
        voice="Puck",
        instructions=f"Du bist ein Assistent. Es ist {time_str}. Fasse dich kurz.",
    )

    # 1. Agent erstellen
    my_agent = Assistant()

    # 2. Session erstellen
    session = AgentSession(llm=model)

    # 3. Event Listener für STT
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

    # 4. STARTEN
    # Korrekte Signatur: erst Agent, dann Raum als Keyword-Argument
    await session.start(my_agent, room=ctx.room)
    
    await session.generate_reply()

if __name__ == "__main__":
    # FEHLER 3 & 4 BEHOBEN: Hier muss 'agents.cli' und 'agents.WorkerOptions' stehen
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))