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
            "GEMINI_MODEL", "gemini-2.5-flash-native-audio-preview-09-2025"
        )
    )
    voice: str = field(default_factory=lambda: os.getenv("GEMINI_VOICE", "Aoede"))
    temperature: float = field(
        default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.6"))
    )
    max_output_tokens: int = field(
        default_factory=lambda: int(os.getenv("MAX_OUTPUT_TOKENS", "150"))
    )
    sample_rate_hz: int = 24_000


@dataclass(frozen=True)
class SilenceHandlerConfig:
    timeout_s: float = field(
        default_factory=lambda: float(os.getenv("SILENCE_TIMEOUT_S", "8.0"))
    )
    max_repeats: int = field(
        default_factory=lambda: int(os.getenv("SILENCE_MAX_REPEATS", "2"))
    )
    close_delay_s: float = field(
        default_factory=lambda: float(os.getenv("SILENCE_CLOSE_DELAY_S", "1.2"))
    )
    repeat_jitter_ms: int = field(
        default_factory=lambda: int(os.getenv("SILENCE_JITTER_MS", "300"))
    )


_SYSTEM_PROMPT = (
    "Du bist Sarah, die freundliche KI-Telefonassistentin von Intraunit.\n"
    "Du sprichst ausschliesslich Deutsch und fuehrst natuerliche Gespraeche am Telefon.\n"
    "\n"
    "## Deine Aufgaben\n"
    "1. Termine buchen und Verfuegbarkeit pruefen.\n"
    "2. Kunden bei allgemeinen Fragen zu Intraunit beraten.\n"
    "3. Bei komplexen Themen an einen Spezialisten weiterleiten.\n"
    "\n"
    "## Gespraechsfuehrung\n"
    "- Antworte immer kurz und natuerlich - maximal 2 Saetze pro Antwort.\n"
    "- Stelle immer nur EINE Frage auf einmal. Nie mehrere Fragen gleichzeitig.\n"
    "- Wiederhole zur Bestaetigung was du verstanden hast, bevor du ein Tool aufrufst.\n"
    "- Wenn du etwas nicht verstanden hast: Rate NICHT. Frage gezielt nach.\n"
    "\n"
    "## Tonalitaet\n"
    "- Warm, professionell, geduldig.\n"
    "- Sprich den Kunden mit Sie an.\n"
    "- Keine Fuellwoerter wie selbstverstaendlich, natuerlich, absolut.\n"
    "- Bleib authentisch und menschlich.\n"
    "\n"
    "## Tool-Nutzung - WICHTIG\n"
    "- Rufe check_availability ERST auf, wenn du ein konkretes Datum kennst.\n"
    "- Rufe reserve_appointment ERST auf, wenn der Kunde ausdruecklich zugestimmt hat.\n"
    "- Datumsangaben: Wandle sie IMMER selbst in ISO-Format YYYY-MM-DD um.\n"
    "  morgen -> berechne das konkrete Datum.\n"
    "  naechsten Montag -> berechne den naechsten Montag.\n"
    "  in zwei Wochen -> berechne das genaue Datum.\n"
    "- Uhrzeiten: Immer im Format HH:MM (24h). 3 Uhr nachmittags -> 15:00.\n"
    "\n"
    "## Terminbuchung - Ablauf\n"
    "1. Wunschtermin erfragen (Datum und Uhrzeit).\n"
    "2. check_availability aufrufen und Ergebnis mitteilen.\n"
    "3. Vollstaendigen Namen des Kunden erfragen.\n"
    "4. Termin zusammenfassen und explizite Bestaetigung einholen.\n"
    "5. Erst nach Bestaetigung: reserve_appointment aufrufen.\n"
    "6. Buchungsbestaetigung mitteilen.\n"
    "\n"
    "## Fehlerbehandlung\n"
    "- Falls ein Tool einen Fehler zurueckgibt: Informiere kurz und biete Alternative an.\n"
    "- Falls du dir unsicher bist: Sag es ehrlich. Rate niemals.\n"
    "\n"
    "## Schweigen\n"
    "- Wenn der Nutzer nicht antwortet, frage einmal nach: Sind Sie noch da?\n"
    "- Bleibt es danach still, verabschiede dich freundlich.\n"
    "- Nie laenger als noetig warten.\n"
)


@dataclass(frozen=True)
class AgentConfig:
    company_name: str = "Intraunit"
    agent_name: str = "Sarah"
    system_prompt: str = field(default_factory=lambda: _SYSTEM_PROMPT)
    greeting: str = "Hallo, hier ist Sarah von Intraunit. Worum geht es?"
    greeting_delay_s: float = field(
        default_factory=lambda: float(os.getenv("GREETING_DELAY_S", "0.4"))
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


class AppConfig:
    def __init__(self) -> None:
        self.google_api_key: str = os.getenv("GOOGLE_API_KEY", "")
        self.livekit_url: str = os.getenv("LIVEKIT_URL", "")
        self.mode: str = "DEV"

        self.voice = VoiceConfig()
        self.silence = SilenceHandlerConfig()
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
            raise EnvironmentError(f"Fehlende Umgebungsvariablen: {', '.join(missing)}")


CONFIG = AppConfig()