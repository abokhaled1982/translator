"""
config.py — Zentrale Konfiguration.
Bereinigt für maximale Performance (kein lokales VAD).
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class VoiceConfig:
    # Das schnellste Modell
    model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    voice: str = "Aoede"
    temperature: float = 0.6

@dataclass(frozen=True)
class SilenceHandlerConfig:
    timeout_s: float = 8.0
    max_repeats: int = 2
    repeat_delay_s: float = 0.4

@dataclass(frozen=True)
class AgentConfig:
    company_name: str = "Intraunit"
    agent_name: str = "Sarah"
    
    system_prompt: str = (
        "Du bist Sarah, die intelligente KI-Assistentin von Intraunit. "
        "Du hast zwei Aufgabenbereiche:"
        "\n1. Terminbuchung & Kundenberatung für Intraunit."
        "\n2. Eine hilfreiche Gesprächspartnerin für allgemeine Fragen sein."
        "\n\nVerhaltensregeln:"
        "\n- Sei immer freundlich, charmant und professionell."
        "\n- Antworte kompakt (maximal 2-3 Sätze)."
        "\n- Wenn du etwas akustisch nicht verstehst: Rate NICHT. Frage höflich nach."
    )

    greeting: str = (
        "Hallo, hier ist Sarah von Intraunit. Worum geht es?"
    )

@dataclass(frozen=True)
class ServerConfig:
    health_port: int = field(default_factory=lambda: int(os.getenv("HEALTH_PORT", "8080")))
    host: str = "0.0.0.0"

@dataclass(frozen=True)
class AppConfig:
    google_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""))
    livekit_url: str = field(default_factory=lambda: os.getenv("LIVEKIT_URL", ""))
    mode: str = "DEV"

    voice: VoiceConfig = field(default_factory=VoiceConfig)
    silence: SilenceHandlerConfig = field(default_factory=SilenceHandlerConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    server: ServerConfig = field(default_factory=ServerConfig)

    def validate(self) -> None:
        missing = []
        if not self.google_api_key: missing.append("GOOGLE_API_KEY")
        if not self.livekit_url: missing.append("LIVEKIT_URL")
        if missing:
            raise EnvironmentError(f"Fehlende Variablen: {', '.join(missing)}")

CONFIG = AppConfig()