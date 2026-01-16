import logging
import os
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv

from livekit import agents, api
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
    AutoSubscribe,
)
from livekit.plugins import google

load_dotenv()
load_dotenv(".env.local")

logger = logging.getLogger("gemini-translator")
logger.setLevel(logging.INFO)

class Assistant(Agent):
    def __init__(self):
        super().__init__(instructions="Du bist ein Dolmetscher.")

async def entrypoint(ctx: JobContext):
    logger.info(f"Verbinde mit Raum: {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # --- DIE MAGIE IST HIER ---
    # Wir geben Gemini strikte Anweisungen, nur zu übersetzen.
    instructions = """
        Du bist ein professioneller Simultandolmetscher.
        Deine Aufgabe:
        1. Höre genau zu, was der Nutzer sagt (meistens auf Arabisch).
        2. Übersetze das Gesagte SOFORT und DIREKT ins Deutsche.
        3. Antworte NICHT auf Fragen. Führe KEINE Unterhaltung.
        4. Gib NUR die deutsche Übersetzung aus.
        
        Beispiel:
        Nutzer (Arabisch): "Marhaban, kayfa haluka?"
        Du (Deutsch): "Hallo, wie geht es dir?"
    """

    model = google.beta.realtime.RealtimeModel(
        model="gemini-2.0-flash-exp",
        api_key=os.getenv("GOOGLE_API_KEY"),
        voice="Puck",
        instructions=instructions,
    )

    # 1. Agent erstellen
    my_agent = Assistant()

    # 2. Session erstellen
    session = AgentSession(llm=model)

    # 3. Event Listener für die Konsole
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
            # Wir formatieren die Ausgabe schön
            if item.role == "user":
                print(f"\n🇸🇦 ARABISCH (gehört): {text}")
            elif item.role == "assistant":
                print(f"🇩🇪 DEUTSCH (Übersetzung): {text}")

    # 4. Starten
    await session.start(my_agent, room=ctx.room)
    
    # Kurze Info an dich (wird gesprochen)
    await session.generate_reply(instructions="Sag kurz auf Deutsch: 'Ich bin bereit zum Übersetzen.'")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))