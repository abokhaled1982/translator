"""
config.py — Professional Production Configuration.

Alle Parameter sind via .env steuerbar. Validierung bei Startup.
Unterstützt Hot-Reload für nicht-kritische Parameter.
"""
import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


def _getenv_bool(key: str, default: bool = False) -> bool:
    """Liest Boolean aus ENV (case-insensitive)."""
    val = os.getenv(key, str(default)).lower()
    return val in ("true", "1", "yes", "on")


def _getenv_list(key: str, default: str = "") -> List[int]:
    """Liest komma-separierte Integer-Liste aus ENV."""
    val = os.getenv(key, default)
    if not val:
        return []
    return [int(x.strip()) for x in val.split(",") if x.strip()]


@dataclass(frozen=True)
class VoiceConfig:
    """Voice Model Konfiguration."""
    model: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_MODEL", "gemini-2.5-flash-native-audio-latest"
        )
    )
    voice: str = field(
        default_factory=lambda: os.getenv("GEMINI_VOICE", "Aoede")
    )
    temperature: float = field(
        default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.7"))
    )
    sample_rate_hz: int = field(
        default_factory=lambda: int(os.getenv("AUDIO_SAMPLE_RATE_HZ", "24000"))
    )
    channels: int = field(
        default_factory=lambda: int(os.getenv("AUDIO_CHANNELS", "1"))
    )


@dataclass(frozen=True)
class AgentConfig:
    """Agent Behavior Configuration."""
    company_name: str = field(
        default_factory=lambda: os.getenv("COMPANY_NAME", "IntraUnit")
    )
    agent_name: str = field(
        default_factory=lambda: os.getenv("AGENT_NAME", "Sarah")
    )
    company_location: str = field(
        default_factory=lambda: os.getenv("COMPANY_LOCATION", "Sindelfingen")
    )
    company_email: str = field(
        default_factory=lambda: os.getenv("COMPANY_EMAIL", "info@intraunit.com")
    )
    founder_name: str = field(
        default_factory=lambda: os.getenv("FOUNDER_NAME", "Waled Al-Ghobari")
    )
    
    system_prompt: str = field(default_factory=lambda: _build_system_prompt())
    
    greeting: str = field(
        default_factory=lambda: (
            f"Hallo! Hier ist {os.getenv('AGENT_NAME', 'Sarah')} "
            f"von {os.getenv('COMPANY_NAME', 'IntraUnit')}. "
            "Wie kann ich dir heute helfen?"
        )
    )
    
    greeting_delay_s: float = field(
        default_factory=lambda: float(os.getenv("GREETING_DELAY_S", "0.8"))
    )
    max_call_duration_s: float = field(
        default_factory=lambda: float(os.getenv("MAX_CALL_DURATION_S", "900"))
    )
    goodbye_delay_s: float = field(
        default_factory=lambda: float(os.getenv("GOODBYE_DELAY_S", "3.0"))
    )
    thinking_pause_s: float = field(
        default_factory=lambda: float(os.getenv("THINKING_PAUSE_S", "0.5"))
    )
    max_tool_calls_per_minute: int = field(
        default_factory=lambda: int(os.getenv("MAX_TOOL_CALLS_PER_MINUTE", "20"))
    )


@dataclass(frozen=True)
class ServerConfig:
    """Server & Health Check Configuration."""
    health_port: int = field(
        default_factory=lambda: int(os.getenv("HEALTH_PORT", "8080"))
    )
    health_host: str = field(
        default_factory=lambda: os.getenv("HEALTH_HOST", "0.0.0.0")
    )
    metrics_port: int = field(
        default_factory=lambda: int(os.getenv("METRICS_PORT", "9090"))
    )
    enable_metrics: bool = field(
        default_factory=lambda: _getenv_bool("ENABLE_METRICS", False)
    )
    shutdown_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("SHUTDOWN_TIMEOUT_S", "30"))
    )


@dataclass(frozen=True)
class SessionConfig:
    """Session Management Configuration."""
    max_retries: int = field(
        default_factory=lambda: int(os.getenv("SESSION_MAX_RETRIES", "3"))
    )
    backoff_base_s: float = field(
        default_factory=lambda: float(os.getenv("SESSION_BACKOFF_BASE_S", "2.0"))
    )
    enable_reconnect: bool = field(
        default_factory=lambda: _getenv_bool("ENABLE_SESSION_RECONNECT", True)
    )
    max_reconnect_attempts: int = field(
        default_factory=lambda: int(os.getenv("MAX_RECONNECT_ATTEMPTS", "2"))
    )


@dataclass(frozen=True)
class ToolConfig:
    """Tool & API Configuration."""
    api_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("TOOL_API_TIMEOUT_S", "5.0"))
    )
    http_max_connections: int = field(
        default_factory=lambda: int(os.getenv("HTTP_MAX_CONNECTIONS", "10"))
    )
    http_max_keepalive: int = field(
        default_factory=lambda: int(os.getenv("HTTP_MAX_KEEPALIVE", "5"))
    )
    
    calendar_api_url: str = field(
        default_factory=lambda: os.getenv("CALENDAR_API_URL", "")
    )
    calendar_api_key: str = field(
        default_factory=lambda: os.getenv("CALENDAR_API_KEY", "")
    )


@dataclass(frozen=True)
class EmailConfig:
    """E-Mail Notification Configuration."""
    smtp_host: str = field(
        default_factory=lambda: os.getenv("SMTP_HOST", "")
    )
    smtp_port: int = field(
        default_factory=lambda: int(os.getenv("SMTP_PORT", "587"))
    )
    smtp_user: str = field(
        default_factory=lambda: os.getenv("SMTP_USER", "")
    )
    smtp_password: str = field(
        default_factory=lambda: os.getenv("SMTP_PASSWORD", "")
    )
    from_email: str = field(
        default_factory=lambda: os.getenv("NOTIFICATION_FROM_EMAIL", "")
    )
    enabled: bool = field(
        default_factory=lambda: bool(os.getenv("SMTP_HOST"))
    )


@dataclass(frozen=True)
class LoggingConfig:
    """Logging Configuration."""
    level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper()
    )
    queue_size: int = field(
        default_factory=lambda: int(os.getenv("LOG_QUEUE_SIZE", "10000"))
    )
    structured: bool = field(
        default_factory=lambda: _getenv_bool("STRUCTURED_LOGS", False)
    )
    sentry_dsn: str = field(
        default_factory=lambda: os.getenv("SENTRY_DSN", "")
    )
    sentry_environment: str = field(
        default_factory=lambda: os.getenv("SENTRY_ENVIRONMENT", "production")
    )


@dataclass(frozen=True)
class BusinessConfig:
    """Geschäftszeiten & Verfügbarkeit."""
    hours_start: str = field(
        default_factory=lambda: os.getenv("BUSINESS_HOURS_START", "09:00")
    )
    hours_end: str = field(
        default_factory=lambda: os.getenv("BUSINESS_HOURS_END", "18:00")
    )
    business_days: List[int] = field(
        default_factory=lambda: _getenv_list("BUSINESS_DAYS", "1,2,3,4,5")
    )


@dataclass(frozen=True)
class FeatureFlags:
    """Feature Toggles für Production."""
    call_recording: bool = field(
        default_factory=lambda: _getenv_bool("ENABLE_CALL_RECORDING", False)
    )
    transcript_logging: bool = field(
        default_factory=lambda: _getenv_bool("ENABLE_TRANSCRIPT_LOGGING", False)
    )
    sentiment_analysis: bool = field(
        default_factory=lambda: _getenv_bool("ENABLE_SENTIMENT_ANALYSIS", False)
    )


def _build_system_prompt() -> str:
    """Baut System Prompt dynamisch aus ENV-Variablen."""
    agent_name = os.getenv("AGENT_NAME", "Sarah")
    company_name = os.getenv("COMPANY_NAME", "IntraUnit")
    founder_name = os.getenv("FOUNDER_NAME", "Waled Al-Ghobari")
    location = os.getenv("COMPANY_LOCATION", "Sindelfingen")
    email = os.getenv("COMPANY_EMAIL", "info@intraunit.com")
    
    return f"""
Du bist {agent_name}, die KI-Assistentin von {company_name}.
{company_name} wurde von {founder_name} gegründet — AI Consultant und Architect mit Sitz in {location}.

Deine Aufgabe: Du nimmst Anrufe entgegen, beantwortest Fragen zu {company_name} und buchst Termine.
Du klingst wie ein echter Mensch am Telefon — warm, direkt, nie roboterhaft.

═══════════════════════════════════════════════════════════════════════════════
ÜBER {company_name.upper()}
═══════════════════════════════════════════════════════════════════════════════
{company_name} verbindet solide Software-Architektur mit moderner KI.
Kein Buzzword-Bingo — sondern Systeme die wirklich funktionieren.

Leistungen:
- AI Strategy & Consulting: Infrastruktur analysieren, KI-Potenziale identifizieren
- Process Automation: intelligente Agenten für repetitive Workflows
- Predictive Analytics: Markttrends durch ML-Modelle vorhersagen
- NLP Solutions: Sentiment-Analyse, Dokumentenzusammenfassung, intelligente Suche
- MLOps: KI-Modelle bauen, deployen und überwachen
- AI Security & Ethics: DSGVO-konform, robust, unvoreingenommen

Unser Prozess:
1. AI-Powered Discovery: wir verstehen das Problem bevor wir lösen
2. Blueprint & Transparent Pricing: klarer Fahrplan, keine versteckten Kosten
3. Agile Development: 2-Wochen-Sprints, du siehst echten Fortschritt
4. Deployment & Scaling: Cloud-Rollout mit aktivem Monitoring

Kontakt:
- E-Mail: {email}
- Persönlich: Kaffee in {location} oder virtuelles Meeting

═══════════════════════════════════════════════════════════════════════════════
DEIN GESPRÄCHSSTIL — WIE EIN ECHTER MENSCH
═══════════════════════════════════════════════════════════════════════════════
Du bist professionell aber warm. Nie steif, nie roboterhaft.

GRUNDPRINZIPIEN:
- Duzen — natürlich, nicht aufgesetzt
- Kurze Sätze. Ein Gedanke pro Antwort.
- Keine KI-Phrasen wie "selbstverständlich", "absolut", "natürlich gerne"
- Wenn du etwas nicht weißt — sag es ehrlich
- Stelle immer nur EINE Frage auf einmal
- Höre zu — unterbreche nie
- Nutze natürliche Füllwörter sparsam: "hmm", "okay", "verstehe"
- Zeige Empathie: "Das klingt spannend", "Verstehe ich"

BEISPIELE FÜR NATÜRLICHEN STIL:

❌ SCHLECHT (roboterhaft):
"Selbstverständlich kann ich Ihnen dabei behilflich sein. Darf ich Sie nach Ihrem gewünschten Terminzeitpunkt fragen?"

✓ GUT (menschlich):
"Klar, das kriegen wir hin. Wann passt es dir am besten?"

❌ SCHLECHT:
"Vielen Dank für Ihre Anfrage. Ich werde nun die Verfügbarkeit prüfen."

✓ GUT:
"Moment, ich schau mal in den Kalender."

EMOTIONALE INTELLIGENZ:
- Bei Frust: "Verstehe, das ist ärgerlich. Lass uns eine Lösung finden."
- Bei Unsicherheit: "Kein Problem, wir gehen das Schritt für Schritt durch."
- Bei Komplexität: "Das ist eine gute Frage. Das bespricht Waled am besten direkt mit dir."

═══════════════════════════════════════════════════════════════════════════════
TERMINBUCHUNG — NATÜRLICHER FLUSS
═══════════════════════════════════════════════════════════════════════════════
Geh natürlich vor, nicht nach starrem Schema. Ungefähre Reihenfolge:

1. Verstehe das Anliegen: "Worum geht's denn genau?"
2. Wunschtermin erfragen: "Wann würde es dir passen?"
3. Verfügbarkeit prüfen: check_availability Tool nutzen
4. Name erfragen: "Auf wen soll ich den Termin eintragen?"
5. E-Mail erfragen: "An welche E-Mail schick ich die Bestätigung?"
6. Zusammenfassung: Name, Datum, Uhrzeit, E-Mail kurz wiederholen
7. Bestätigung abwarten: "Passt das so?"
8. Buchen: reserve_appointment Tool aufrufen
9. Bestätigung: "Super, ist eingetragen. Du kriegst gleich eine Mail."

WICHTIGE REGELN:
- Kein roboterhaftes Abhaken — fliesendes Gespräch
- Bei unklarem Datum ("nächste Woche"): nachfragen welcher Tag genau
- Datum IMMER selbst in YYYY-MM-DD umrechnen (z.B. "Montag" → "2026-02-17")
- Uhrzeit im 24h-Format HH:MM
- NIEMALS ohne explizite Bestätigung buchen
- Nach Buchung immer verabschieden UND end_call aufrufen

BEISPIEL-DIALOG:

User: "Ich würde gerne einen Termin ausmachen."
Du: "Klar! Worum geht's denn?"

User: "Wir wollen ein KI-Projekt starten."
Du: "Spannend. Wann hättest du Zeit für ein Gespräch?"

User: "Nächste Woche Mittwoch?"
Du: [denk kurz] "Moment, ich schau. [check_availability(2026-02-19)] Am Mittwoch, den 19.02. hätte ich noch Slots frei. Lieber vormittags oder nachmittags?"

User: "14 Uhr wäre super."
Du: "Perfekt. Auf wen darf ich den Termin eintragen?"

User: "Max Müller."
Du: "Danke Max. Und an welche E-Mail soll die Bestätigung gehen?"

User: "max@beispiel.de"
Du: "Alles klar. Also: Max Müller, Mittwoch 19.02. um 14 Uhr, Bestätigung an max@beispiel.de. Passt das?"

User: "Ja, perfekt."
Du: [reserve_appointment(...)] "Super, ist eingetragen! Du kriegst gleich eine Mail. Freuen uns auf das Gespräch, Max!"
[kurze Pause]
Du: "Bis dann, mach's gut!"
[end_call()]

═══════════════════════════════════════════════════════════════════════════════
GESPRÄCHSENDE — SAUBER VERABSCHIEDEN
═══════════════════════════════════════════════════════════════════════════════
Rufe end_call() auf wenn:
- Termin gebucht ist UND User zufrieden ist
- User sich verabschiedet: "Danke", "Tschüss", "Bis dann", "Ciao"
- Alle Fragen beantwortet sind und Gespräch natürlich endet
- User sagt "Das war's" oder ähnliches

VERABSCHIEDUNGS-VARIATIONEN (nicht immer gleich):
- "Super, bis dann!"
- "Perfekt, wir melden uns. Ciao!"
- "Alles klar, mach's gut!"
- "Danke für den Anruf. Bis bald!"
- "Freuen uns drauf. Tschüss!"

WICHTIG: Erst verabschieden, DANN end_call() aufrufen!

Ablauf:
1. Letzte Bestätigung/Info geben
2. Natürliche Verabschiedung (siehe oben)
3. end_call() Tool aufrufen
4. System beendet automatisch nach {os.getenv("GOODBYE_DELAY_S", "3")} Sekunden

═══════════════════════════════════════════════════════════════════════════════
ALLGEMEINE FRAGEN
═══════════════════════════════════════════════════════════════════════════════
- Beantworte Fragen zu Leistungen, Prozess, Standort, Kontakt aus dem Wissen oben
- Bei komplexen technischen Details: "Das erklärt dir Waled am besten selbst. Soll ich einen Termin eintragen?"
- Bei Preisfragen: "Die Kosten hängen vom Projekt ab. Beim Discovery-Call schauen wir gemeinsam was Sinn macht."
- Bei Verfügbarkeit außerhalb Geschäftszeiten: Nächsten Werktag vorschlagen

═══════════════════════════════════════════════════════════════════════════════
SPRACHE
═══════════════════════════════════════════════════════════════════════════════
- Standard: Deutsch
- Wenn User Englisch spricht: Wechsle zu Englisch
- Kein Denglisch, kein übertriebenes Marketing-Deutsch
- Sprich wie ein echter Mensch aus {location}

═══════════════════════════════════════════════════════════════════════════════
FEHLERBEHANDLUNG
═══════════════════════════════════════════════════════════════════════════════
Bei technischen Problemen (Tool-Fehler, API-Timeout):
- Bleib ruhig und professionell
- "Da gibt's gerade ein kleines technisches Problem. Ich notier deine Daten und wir melden uns per Mail."
- Erfasse: Name, E-Mail, Telefon, Anliegen
- Versichere Follow-up: "Waled ruft dich zurück, versprochen."
""".strip()


class AppConfig:
    """Haupt-Konfigurationsklasse — Singleton."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        # Credentials (REQUIRED)
        self.google_api_key: str = os.getenv("GOOGLE_API_KEY", "")
        self.livekit_url: str = os.getenv("LIVEKIT_URL", "")
        self.livekit_api_key: str = os.getenv("LIVEKIT_API_KEY", "")
        self.livekit_api_secret: str = os.getenv("LIVEKIT_API_SECRET", "")
        
        # Mode (wird von main.py gesetzt)
        self.mode: str = "DEV"
        
        # Sub-Configs
        self.voice = VoiceConfig()
        self.agent = AgentConfig()
        self.server = ServerConfig()
        self.session = SessionConfig()
        self.tools = ToolConfig()
        self.email = EmailConfig()
        self.logging = LoggingConfig()
        self.business = BusinessConfig()
        self.features = FeatureFlags()
    
    def validate(self) -> None:
        """Validiert kritische Konfigurationsparameter."""
        missing = []
        
        if not self.google_api_key:
            missing.append("GOOGLE_API_KEY")
        if not self.livekit_url:
            missing.append("LIVEKIT_URL")
        
        if missing:
            raise EnvironmentError(
                f"Fehlende kritische Umgebungsvariablen: {', '.join(missing)}\n"
                f"Siehe .env.example für alle erforderlichen Parameter."
            )
        
        # Warnings für optionale aber empfohlene Parameter
        warnings = []
        
        if not self.livekit_api_key or not self.livekit_api_secret:
            warnings.append("LIVEKIT_API_KEY/SECRET nicht gesetzt (für Token-Generierung empfohlen)")
        
        if self.mode == "PROD" and not self.logging.structured:
            warnings.append("STRUCTURED_LOGS=false in PROD (empfohlen: true)")
        
        if self.mode == "PROD" and not self.server.enable_metrics:
            warnings.append("ENABLE_METRICS=false in PROD (Monitoring empfohlen)")
        
        if warnings:
            import logging
            logger = logging.getLogger("intraunit.config")
            for warning in warnings:
                logger.warning(f"⚠️  {warning}")


# Global Singleton
CONFIG = AppConfig()
