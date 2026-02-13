import logging
import os
import sys
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Annotated
from dotenv import load_dotenv
from datetime import datetime, date

# LiveKit Core & Plugins
from livekit.agents import (
    JobContext,
    WorkerOptions,
    cli,
    AutoSubscribe,
    llm,
    RunContext
)
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google, silero

load_dotenv()

# ---------------------------------------------------------------------------
# 1. STARTMODUS
#    python .\src\voice_agent.py console   → DEV:  lokaler Room, Mikrofon/Lautsprecher
#                                              Icon-Ausgabe im Terminal (wie agent.py)
#    python .\src\voice_agent.py prod      → PROD: Worker wartet auf eingehende Jobs,
#                                              JSON-Logs, keine Konsolenausgabe
# ---------------------------------------------------------------------------
_RAW_CMD = sys.argv[1].lower() if len(sys.argv) > 1 else "console"

if _RAW_CMD in ("prod", "start"):
    APP_MODE = "PROD"
    sys.argv[1] = "start"            # LiveKit Produktions-Worker (wartet auf Jobs)

elif _RAW_CMD in ("console", "dev"):
    APP_MODE = "DEV"
    # "dev" startet einen lokalen Room direkt im Terminal
    # Mikrofon/Lautsprecher werden automatisch genutzt, kein Browser noetig
    sys.argv[1] = "dev"

else:
    print(f"[FEHLER] Unbekannter Startmodus: '{_RAW_CMD}'. Erlaubt: console | prod", file=sys.stderr)
    sys.exit(1)

HTTP_HEALTH_PORT = int(os.getenv("HEALTH_PORT", 8080))

# ---------------------------------------------------------------------------
# 2. STARTUP-VALIDIERUNG (schlägt früh fehl, nicht mitten im Gespräch)
# ---------------------------------------------------------------------------
def _validate_env():
    required = {"GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY")}
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"[FEHLER] Fehlende Umgebungsvariablen: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

_validate_env()

# ---------------------------------------------------------------------------
# 3. LOGGING
#    PROD → JSON (maschinenlesbar, kein Transcript-Rauschen)
#    DEV  → Lesbares Format mit Debug-Level
# ---------------------------------------------------------------------------
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
        return json.dumps(log_record, ensure_ascii=False)

logger = logging.getLogger("voice-agent")
_handler = logging.StreamHandler()

if APP_MODE == "PROD":
    logger.setLevel(logging.INFO)
    _handler.setFormatter(JsonFormatter())
    # In Prod: stdout nur für strukturierte Logs, stderr für kritische Fehler
    _handler.stream = sys.stdout
else:
    logger.setLevel(logging.DEBUG)
    _handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logger.addHandler(_handler)
logger.propagate = False

logger.info(f"Starte im Modus: {APP_MODE}")

# ---------------------------------------------------------------------------
# 4. HEALTH CHECK SERVER (nur in PROD relevant für Docker/K8s)
#    In DEV trotzdem gestartet, schadet nicht.
# ---------------------------------------------------------------------------
class AgentHealth:
    healthy: bool = True

_health = AgentHealth()

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if _health.healthy:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"UNHEALTHY")

    def log_message(self, format, *args):
        pass  # Kein Konsolen-Spam durch K8s-Probes

def start_health_check_server():
    try:
        server = HTTPServer(('0.0.0.0', HTTP_HEALTH_PORT), HealthCheckHandler)
        logger.info(f"Health Check Server läuft auf Port {HTTP_HEALTH_PORT}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Konnte Health Check Server nicht starten: {e}")

# ---------------------------------------------------------------------------
# 5. AGENT LOGIK
# ---------------------------------------------------------------------------
class SalesAssistant(Agent):
    def __init__(self):
        super().__init__(
            instructions=(
                "Du bist ein proaktiver Vertriebs-Sachbearbeiter für Intraunit. "
                "Dein Ziel ist es, den Kunden professionell zu beraten und für einen Termin zu gewinnen (Akquise). "
                "1. Sei freundlich, kompetent und verbindlich. Antworte KURZ – maximal 2-3 Sätze pro Antwort. "
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
        appointment_date: Annotated[str, "Das Datum des Termins (ISO Format YYYY-MM-DD)"],
        appointment_time: Annotated[str, "Die Uhrzeit des Termins (HH:MM)"],
    ):
        """Bucht einen Termin verbindlich, nachdem der Kunde zugestimmt hat."""
        logger.info(f"ACTION: Reserve Appointment - {name}, {appointment_date}, {appointment_time}")

        try:
            # Datum validieren bevor API-Call
            parsed_date = datetime.strptime(appointment_date, "%Y-%m-%d").date()
            if parsed_date < date.today():
                return "Dieses Datum liegt in der Vergangenheit. Bitte nennen Sie mir ein zukünftiges Datum."

            # TODO: Hier echten API-Call einfügen, z.B.:
            # await calendar_api.post("/appointments", json={...})

            return (
                f"Vielen Dank, {name}. Ihr Termin am {appointment_date} um {appointment_time} Uhr "
                "wurde fest gebucht. Die Bestätigung ist per E-Mail unterwegs."
            )

        except ValueError:
            logger.warning(f"Ungültiges Datumsformat erhalten: {appointment_date}")
            return "Das Datum konnte ich leider nicht lesen. Könnten Sie es bitte im Format Tag.Monat.Jahr nennen?"
        except ConnectionError as ce:
            logger.error(f"Datenbankfehler bei Reservierung: {ce}")
            return "Ich habe gerade Zugriffsprobleme auf meinen Kalender. Ich notiere die Daten und trage es manuell nach."
        except Exception as e:
            logger.error(f"Unerwarteter Fehler bei Reservierung: {e}", exc_info=True)
            return "Es gab einen technischen Fehler. Ein Mitarbeiter ruft Sie zur Bestätigung zurück."

    @llm.function_tool
    async def check_availability(
        self,
        context: RunContext,
        requested_date: Annotated[str, "Das angefragte Datum im ISO Format YYYY-MM-DD"],
    ):
        """Prüft Verfügbarkeit für ein Datum. Erkennt Wochenenden automatisch."""
        try:
            logger.info(f"ACTION: Check Availability - {requested_date}")

            parsed = datetime.strptime(requested_date, "%Y-%m-%d").date()

            # Wochenende prüfen (0=Montag, 6=Sonntag)
            if parsed.weekday() == 6:
                next_monday = parsed.replace(day=parsed.day + 1)
                return f"Am Sonntag haben wir Ruhetag. Passt es Ihnen am Montag, dem {next_monday.strftime('%d.%m.%Y')}?"
            if parsed.weekday() == 5:
                next_monday = parsed.replace(day=parsed.day + 2)
                return f"Samstags sind wir leider nicht erreichbar. Wie wäre es mit Montag, dem {next_monday.strftime('%d.%m.%Y')}?"

            # TODO: Echte Kalender-API hier einbinden
            return f"Am {parsed.strftime('%d.%m.%Y')} habe ich noch freie Slots. Lieber Vormittags oder Nachmittags?"

        except ValueError:
            logger.warning(f"Ungültiges Datumsformat in check_availability: {requested_date}")
            return "Das Datum konnte ich nicht lesen. Bitte nennen Sie mir Tag, Monat und Jahr."
        except Exception as e:
            logger.error(f"Fehler bei Verfügbarkeitsprüfung: {e}", exc_info=True)
            return "Ich kann den Kalender gerade nicht einsehen. Nennen Sie mir Ihren Wunschtermin, wir machen das möglich."

# ---------------------------------------------------------------------------
# 6. ENTRYPOINT & SESSION LIFECYCLE
# ---------------------------------------------------------------------------
async def entrypoint(ctx: JobContext):
    logger.info(f"Starte Session im Raum: {ctx.room.name}")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    model = google.realtime.RealtimeModel(
        model="gemini-2.5-flash-native-audio-preview-12-2025",
        api_key=os.getenv("GOOGLE_API_KEY"),
        voice="Puck",
        temperature=0.4,  # 0.6 → 0.4: präzisere, kürzere Antworten
    )

    vad = silero.VAD.load(
        min_silence_duration=0.4,   # 0.8 → 0.4s: kürzere Pause nach dem Sprechen
        min_speech_duration=0.1,    # 0.3 → 0.1s: kurze Silben sofort erkannt
    )

    agent_worker = SalesAssistant()
    session = AgentSession(llm=model, vad=vad)

    # Konsolenausgabe: NUR im DEV-Modus, in PROD stdout komplett deaktivieren
    if APP_MODE == "DEV":
        @session.on("conversation_item_added")
        def on_item(event):
            item = getattr(event, 'item', event)
            text = ""
            if hasattr(item, 'content'):
                if isinstance(item.content, list):
                    for part in item.content:
                        if hasattr(part, 'text'):
                            text += part.text
                        elif isinstance(part, str):
                            text += part
                elif isinstance(item.content, str):
                    text = item.content

            if text:
                role_icon = "\U0001f5e3\ufe0f  DU" if item.role == "user" else "\U0001f916 AGENT"
                print(f"\n{role_icon}: {text}", flush=True)
    else:
        # PROD: stdout → /dev/null, damit keine print()-Ausgaben aus Libraries
        # oder zukünftigem Code die strukturierten JSON-Logs verschmutzen.
        # Der Logger selbst schreibt weiterhin (hält das originale stdout-Handle).
        import io
        sys.stdout = io.TextIOWrapper(open(os.devnull, "wb"))

    await session.start(agent_worker, room=ctx.room)

    await session.generate_reply(
        instructions=(
            "Begrüße den Kunden professionell bei Intraunit. "
            "Stelle dich als digitaler Assistent vor und frage offen, wie du unterstützen kannst."
        )
    )

# ---------------------------------------------------------------------------
# 7. MAIN
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Health Check immer starten (K8s braucht das auch im Dev)
    health_thread = threading.Thread(target=start_health_check_server, daemon=True)
    health_thread.start()

    try:
        cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
    except KeyboardInterrupt:
        logger.info("Agent wird beendet (KeyboardInterrupt).")
    except Exception as e:
        _health.healthy = False
        logger.critical(f"Kritischer Fehler im Main-Loop: {e}", exc_info=True)
        sys.exit(1)