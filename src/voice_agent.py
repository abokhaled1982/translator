import logging
import os
import asyncio
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Annotated
from dotenv import load_dotenv
from datetime import datetime

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

# --- 1. KONFIGURATION & ENVIRONMENT ---
APP_MODE = os.getenv("APP_MODE", "DEV").upper() # "DEV" oder "PROD"
HTTP_HEALTH_PORT = int(os.getenv("HEALTH_PORT", 8080))

# --- 2. PROFESSIONAL LOGGING (JSON für Prod) ---
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

logger = logging.getLogger("voice-agent")
handler = logging.StreamHandler()

if APP_MODE == "PROD":
    logger.setLevel(logging.INFO)
    handler.setFormatter(JsonFormatter()) # JSON Logs für Maschinenlesbarkeit
else:
    logger.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')) # Lesbar für Menschen

logger.addHandler(handler)
# Verhindere doppelte Logs durch Root-Logger
logger.propagate = False 

# --- 3. HEALTH CHECK SERVER (Für Docker/K8s) ---
# Ein einfacher Server, der 200 OK zurückgibt, solange der Prozess läuft.
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    
    # Logging des Healthchecks unterdrücken, sonst müllt das die Konsole voll
    def log_message(self, format, *args):
        pass

def start_health_check_server():
    try:
        server = HTTPServer(('0.0.0.0', HTTP_HEALTH_PORT), HealthCheckHandler)
        logger.info(f"Health Check Server läuft auf Port {HTTP_HEALTH_PORT}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Konnte Health Check Server nicht starten: {e}")

# --- 4. DER AGENT (SACHBEARBEITER LOGIK) ---
class SalesAssistant(Agent):
    def __init__(self):
        super().__init__(
            instructions=(
                "Du bist ein proaktiver Vertriebs-Sachbearbeiter für Intraunit. "
                "Dein Ziel ist es, den Kunden professionell zu beraten und für einen Termin zu gewinnen (Akquise). "
                "1. Sei freundlich, kompetent und verbindlich. "
                "2. Wenn der Kunde zögert, hebe die Vorteile eines persönlichen Gesprächs hervor. "
                "3. Frage gezielt nach Bedarf, Name, Datum und Uhrzeit. "
                "4. Wenn technische Fragen kommen, auf die du keine Antwort hast, biete an, "
                "dass ein Spezialist dies im Termin klärt. Erfinde keine Fakten. "
                "5. Bestätige den Termin am Ende präzise."
            )
        )

    @llm.function_tool
    async def reserve_appointment(
        self,
        context: RunContext,
        name: Annotated[str, "Der vollständige Name des Kunden"],
        date: Annotated[str, "Das Datum des Termins (ISO Format YYYY-MM-DD)"],
        time: Annotated[str, "Die Uhrzeit des Termins (HH:MM)"],
    ):
        """Bucht einen Termin verbindlich, nachdem der Kunde zugestimmt hat."""
        logger.info(f"ACTION: Reserve Appointment - {name}, {date}, {time}")
        
        # --- ERROR HANDLING & NETZWERK SIMULATION ---
        try:
            # Hier würde der echte API Call stehen (z.B. await api.post(...))
            # Wir simulieren einen Netzwerkfehler in 1 von 100 Fällen
            import random
            if random.random() < 0.01: 
                raise ConnectionError("Simulierter Datenbank-Timeout")

            # Erfolgsfall
            return (
                f"Vielen Dank, Herr/Frau {name}. Der Termin am {date} um {time} "
                "wurde fest gebucht und die Bestätigung ist per E-Mail unterwegs."
            )

        except ConnectionError as ce:
            logger.error(f"Datenbankfehler bei Reservierung: {ce}")
            return "Entschuldigung, ich habe gerade Zugriffsprobleme auf meinen Kalender. Können wir die Daten kurz festhalten? Ich trage es manuell nach."
        except Exception as e:
            logger.error(f"Unerwarteter Fehler: {e}")
            return "Es gab einen kleinen technischen Fehler. Ein Mitarbeiter ruft Sie zur Bestätigung zurück."

    @llm.function_tool
    async def check_availability(
        self,
        context: RunContext,
        date: Annotated[str, "Das angefragte Datum"],
    ):
        """Prüft Verfügbarkeit. Erkennt Sonntage und Feiertage."""
        try:
            # Einfache Logik, später durch API ersetzen
            logger.info(f"ACTION: Check Availability - {date}")
            if "sonntag" in date.lower():
                return "Am Sonntag haben wir Ruhetag. Passt es Ihnen vielleicht am Montag darauf?"
            return f"Am {date} habe ich noch freie Slots. Vormittags oder lieber Nachmittags?"
        except Exception as e:
            logger.error(f"Fehler bei Verfügbarkeit: {e}")
            return "Ich kann den Kalender gerade nicht einsehen, aber sagen Sie mir Ihren Wunschtermin, wir machen das möglich."

# --- 5. ENTRYPOINT & LIFECYCLE ---
async def entrypoint(ctx: JobContext):
    logger.info(f"--- Starte Session im Raum: {ctx.room.name} ---")
    
    # Verbindung herstellen
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    
    # Model Setup
    model = google.realtime.RealtimeModel(
        model="gemini-2.5-flash-native-audio-preview-12-2025", 
        api_key=os.getenv("GOOGLE_API_KEY"),
        voice="Puck", # Puck klingt oft energetischer/jünger
        temperature=0.6, # Etwas kreativer für Verkaufsgespräche, aber nicht zu wild
    )

    # VAD Setup (Optimiert für weniger Unterbrechungen)
    vad = silero.VAD.load(
        min_silence_duration=0.8, # Warte etwas länger, ob der Kunde fertig ist (höflicher)
        min_speech_duration=0.3,
    )

    agent_worker = SalesAssistant()
    session = AgentSession(llm=model, vad=vad)

    # Event Logging für Debugging
    @session.on("conversation_item_added")
    def on_item(event):
        if APP_MODE == "DEV": # Nur im Dev Mode den Chat voll loggen
            if hasattr(event, 'item'):
                role = event.item.role
                content = "..." # Inhalt kürzen oder voll anzeigen
                if hasattr(event.item, 'content'):
                    content = event.item.content
                logger.debug(f"TRANSCRIPT [{role}]: {content}")

    # Start
    await session.start(agent_worker, room=ctx.room)
    
    # Aktive Vertriebs-Begrüßung
    await session.generate_reply(
        instructions="Begrüße den Kunden professionell bei Intraunit. Stelle dich als digitaler Assistent vor und frage offen, wie du unterstützen kannst."
    )

if __name__ == "__main__":
    # Health Check in separatem Thread starten (blockiert nicht den Main Loop)
    health_thread = threading.Thread(target=start_health_check_server, daemon=True)
    health_thread.start()

    # Agent starten
    try:
        cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
    except KeyboardInterrupt:
        logger.info("Agent wird beendet...")
    except Exception as e:
        logger.critical(f"Kritischer Fehler im Main-Loop: {e}", exc_info=True)