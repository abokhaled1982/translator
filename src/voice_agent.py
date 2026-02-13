import logging
import os
import asyncio
import json
from datetime import datetime, timezone
from typing import Annotated
from dotenv import load_dotenv

# LiveKit Core & Plugins
from livekit.agents import (
    JobContext, 
    WorkerOptions, 
    cli, 
    AutoSubscribe, 
    llm, 
    function_tool, 
    RunContext
)
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google, silero

load_dotenv()

# --- LOGGING KONFIGURATION ---
# Wir nutzen Umgebungsvariablen für den Modus
APP_MODE = os.getenv("APP_MODE", "DEV").upper()
log_level = logging.INFO if APP_MODE == "PROD" else logging.DEBUG

logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("voice-agent")

from typing import Annotated
from livekit.agents import llm, function_tool, RunContext

class MyAssistant(Agent):
    def __init__(self):
        super().__init__(
            instructions=(
                "Du bist ein Termin-Assistent für Intraunit. "
                "Deine Aufgabe ist es, Termine freundlich entgegenzunehmen. "
                "Frage aktiv nach dem Namen, dem gewünschten Datum und der Uhrzeit. "
                "Bestätige am Ende alle Daten, bevor du die Reservierung buchst."
            )
        )

    @llm.function_tool
    async def reserve_appointment(
        self,
        context: RunContext,
        name: Annotated[str, "Der vollständige Name des Kunden"],
        date: Annotated[str, "Das Datum des Termins (z.B. 2024-05-20)"],
        time: Annotated[str, "Die Uhrzeit des Termins (z.B. 14:30)"],
    ):
        """
        Diese Funktion wird aufgerufen, um einen Termin final zu buchen, 
        nachdem der Nutzer alle Daten bestätigt hat.
        """
        logger.info(f"Reservierung wird verarbeitet: {name} am {date} um {time}")
        
        # Hier simulieren wir den Versand an die E-Mail
        target_email = "info@intraunit.de"
        
        # Simulation einer Datenbank/API-Logik
        success_message = (
            f"Termin für {name} am {date} um {time} wurde erfolgreich im System vermerkt. "
            f"Eine Bestätigung wurde intern an {target_email} gesendet."
        )
        
        # Du könntest hier auch session.say() nutzen, aber der Return-Wert 
        # wird von Gemini automatisch in die Antwort eingebaut.
        return success_message

    @llm.function_tool
    async def check_availability(
        self,
        context: RunContext,
        date: Annotated[str, "Das angefragte Datum"],
    ):
        """Prüft, ob an einem bestimmten Tag noch Termine frei sind."""
        # Simulation: Sonntags ist immer zu
        if "sonntag" in date.lower():
            return "Leider haben wir am Sonntag geschlossen."
        
        return f"Am {date} sind aktuell noch Termine am Vormittag und Nachmittag frei."
async def entrypoint(ctx: JobContext):
    logger.info(f"--- Starte Agent im {APP_MODE} Modus ---")
    
    # Verbindung zum Raum herstellen
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    
    # Gemini Realtime Model Setup
    model = google.realtime.RealtimeModel(
        model="gemini-2.5-flash-native-audio-preview-12-2025", # oder deine spezifische Version
        api_key=os.getenv("GOOGLE_API_KEY"),
        voice="Puck",
    )

    # Voice Activity Detection (VAD)
    vad = silero.VAD.load(
        min_silence_duration=0.5,
        min_speech_duration=0.2,
    )

    # Agent und Session initialisieren
    my_agent = MyAssistant()
    session = AgentSession(llm=model, vad=vad)

    # Konsolen-Output für die Unterhaltung
    @session.on("conversation_item_added")
    def on_item(event):
        # Wir nutzen das Event-Objekt um den Text zu extrahieren
        if hasattr(event, 'item') and event.item.role == "user":
            logger.info(f"🗣️ Nutzer: {event.item.content}")
        elif hasattr(event, 'item') and event.item.role == "assistant":
            logger.info(f"🤖 Agent: {event.item.content}")

    # Start der Session
    await session.start(my_agent, room=ctx.room)
    
    # Proaktive Begrüßung beim Beitreten
   # Ersetze:
# await session.say("Hallo! Ich bin dein neuer Voice Agent. Wie kann ich dir heute helfen?")

# Durch:
    await session.generate_reply(
        instructions="Begrüße den Nutzer kurz und frage, wie du helfen kannst."
    )

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))