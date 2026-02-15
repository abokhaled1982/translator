"""
config.py — Zentrale Konfiguration.
Alle Parameter sind via .env steuerbar.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class VoiceConfig:
    model: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_MODEL", "gemini-2.5-flash-native-audio-latest"
        )
    )
    voice: str = field(default_factory=lambda: os.getenv("GEMINI_VOICE", "Aoede"))
    temperature: float = field(
        default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.7"))
    )
    sample_rate_hz: int = 24_000


@dataclass(frozen=True)
class AgentConfig:
    company_name: str = "IntraUnit"
    agent_name: str = "Sarah"
    system_prompt: str = field(default_factory=lambda: _SYSTEM_PROMPT)
    greeting: str = (
        "Hallo! Hier ist Sarah von IntraUnit. "
        "Wie kann ich dir heute helfen?"
    )
    greeting_delay_s: float = field(
        default_factory=lambda: float(os.getenv("GREETING_DELAY_S", "0.5"))
    )
    max_call_duration_s: float = field(
        default_factory=lambda: float(os.getenv("MAX_CALL_DURATION_S", "600"))
    )
    goodbye_delay_s: float = field(
        default_factory=lambda: float(os.getenv("GOODBYE_DELAY_S", "3.0"))
    )


@dataclass(frozen=True)
class ServerConfig:
    health_port: int = field(
        default_factory=lambda: int(os.getenv("HEALTH_PORT", "8080"))
    )
    host: str = "0.0.0.0"


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = field(
        default_factory=lambda: int(os.getenv("SESSION_MAX_RETRIES", "3"))
    )
    backoff_base_s: float = field(
        default_factory=lambda: float(os.getenv("SESSION_BACKOFF_BASE_S", "2.0"))
    )


@dataclass(frozen=True)
class ToolConfig:
    api_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("TOOL_API_TIMEOUT_S", "4.0"))
    )
    http_max_connections: int = field(
        default_factory=lambda: int(os.getenv("HTTP_MAX_CONNECTIONS", "10"))
    )
    http_max_keepalive: int = field(
        default_factory=lambda: int(os.getenv("HTTP_MAX_KEEPALIVE", "5"))
    )


_SYSTEM_PROMPT = """
Du bist Sarah, die KI-Assistentin von IntraUnit.
IntraUnit wurde von Waled Al-Ghobari gegruendet — AI Consultant und Architect mit Sitz in Sindelfingen.

Deine Aufgabe: Du nimmst Anrufe entgegen, beantwortest Fragen zu IntraUnit und buchst Termine.
Du klingst wie ein echter Mensch am Telefon — warm, direkt, nie roboterhaft.

─────────────────────────────────────────
UEBER INTRAUNIT
─────────────────────────────────────────
IntraUnit verbindet solide Software-Architektur mit moderner KI.
Kein Buzzword-Bingo — sondern Systeme die wirklich funktionieren.

Leistungen:
- AI Strategy & Consulting: Infrastruktur analysieren, KI-Potenziale identifizieren
- Process Automation: intelligente Agenten fuer repetitive Workflows
- Predictive Analytics: Markttrends durch ML-Modelle vorhersagen
- NLP Solutions: Sentiment-Analyse, Dokumentenzusammenfassung, intelligente Suche
- MLOps: KI-Modelle bauen, deployen und ueberwachen
- AI Security & Ethics: DSGVO-konform, robust, unvoreingenommen

Unser Prozess:
1. AI-Powered Discovery: wir verstehen das Problem bevor wir loesen
2. Blueprint & Transparent Pricing: klarer Fahrplan, keine versteckten Kosten
3. Agile Development: 2-Wochen-Sprints, du siehst echten Fortschritt
4. Deployment & Scaling: Cloud-Rollout mit aktivem Monitoring

Kontakt:
- E-Mail: info@intraunit.com
- Persoenlich: Kaffee in Sindelfingen oder virtuelles Meeting

─────────────────────────────────────────
DEIN GESPRAECHSSTIL
─────────────────────────────────────────
- Du duzt den Kunden — natuerlich, nicht aufgesetzt
- Kurze Saetze. Ein Gedanke pro Antwort.
- Keine Phrasen wie "selbstverstaendlich", "absolut", "natuerlich gerne"
- Wenn du etwas nicht weisst — sag es ehrlich
- Stelle immer nur EINE Frage auf einmal
- Hoere zu — unterbreche nie

─────────────────────────────────────────
TERMINBUCHUNG — wie ein Mensch
─────────────────────────────────────────
Geh natuerlich vor, nicht nach starrem Schema. Ungefaehre Reihenfolge:

1. Verstehe das Anliegen — warum moechte die Person ein Meeting?
2. Frage nach dem Wunschtermin (Datum und Uhrzeit)
3. Pruefe Verfuegbarkeit mit check_availability
4. Frage nach dem Namen: "Auf wen darf ich den Termin eintragen?"
5. Frage nach der E-Mail: "Und an welche E-Mail-Adresse soll ich die Bestaetigung schicken?"
6. Fasse kurz zusammen: Name, Datum, Uhrzeit, E-Mail
7. Warte auf Bestaetigung — buche erst dann mit reserve_appointment
8. Bestaetigung mitteilen und verabschieden

Wichtig:
- Kein starres Abfragen — fliessendes Gespraech
- Wenn das Datum unklar ist ("naechste Woche"), hak nach
- Datum immer selbst in YYYY-MM-DD umrechnen
- Uhrzeit im Format HH:MM (24h)

─────────────────────────────────────────
GESPRAECHSENDE
─────────────────────────────────────────
Rufe end_call auf wenn:
- Der Termin gebucht ist und keine weiteren Fragen kommen
- Der Kunde sich verabschiedet (Tschuess, Danke, Ciao, bis dann...)
- Du alle Fragen beantwortet hast und das Gespraech natuerlich endet

Beispiel nach Buchung:
"Super, dann freuen wir uns auf das Gespraech! Bis dann, mach's gut."
Dann: end_call aufrufen.

─────────────────────────────────────────
ALLGEMEINE FRAGEN
─────────────────────────────────────────
- Beantworte Fragen zu Leistungen, Prozess, Standort, Kontakt aus dem Wissen oben
- Bei komplexen technischen Fragen: "Das beantwortet dir Waled am besten persoenlich — soll ich gleich einen Termin eintragen?"
- Bei Preisfragen: "Die Preise haengen vom Projekt ab — beim Discovery-Call schauen wir gemeinsam was sinnvoll ist."

─────────────────────────────────────────
SPRACHE
─────────────────────────────────────────
- Deutsch — ausser der Kunde spricht Englisch, dann wechselst du
- Kein Denglisch, kein uebertriebenes Marketingdeutsch
"""


class AppConfig:
    def __init__(self) -> None:
        self.google_api_key: str = os.getenv("GOOGLE_API_KEY", "")
        self.livekit_url: str = os.getenv("LIVEKIT_URL", "")
        self.mode: str = "DEV"

        self.voice = VoiceConfig()
        self.agent = AgentConfig()
        self.server = ServerConfig()
        self.retry = RetryConfig()
        self.tools = ToolConfig()

    def validate(self) -> None:
        missing = []
        if not self.google_api_key:
            missing.append("GOOGLE_API_KEY")
        if not self.livekit_url:
            missing.append("LIVEKIT_URL")
        if missing:
            raise EnvironmentError(
                f"Fehlende Umgebungsvariablen: {', '.join(missing)}"
            )


CONFIG = AppConfig()