"""
config.py — Zentrale Konfiguration für den Intraunit Voice Agent.
Alle Einstellungen an einem Ort. Keine hardcodierten Werte im Code.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class VoiceConfig:
    model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    voice: str = "Puck"
    temperature: float = 0.4          # Niedrig = schnelle, präzise Antworten


@dataclass(frozen=True)
class VADConfig:
    min_silence_duration: float = 0.25   # Sekunden Stille bis Antwort startet
    min_speech_duration: float = 0.15    # Mindest-Sprechdauer zur Erkennung
    prefix_padding_duration: float = 0.1 # Audio-Puffer vor Sprache


@dataclass(frozen=True)
class AgentConfig:
    company_name: str = "Intraunit"
    agent_name: str = "digitaler Vertriebs-Assistent"

    # System-Prompt: kompakt, handlungsorientiert
    system_prompt: str = (
        "Du bist der digitale Vertriebs-Assistent von Intraunit. "
        "Deine Aufgabe: Kunden professionell beraten und Termine buchen. "
        "\n\nVerhaltensregeln:"
        "\n- Antworte IMMER in maximal 2 Sätzen. Keine langen Monologe."
        "\n- Kündige JEDE Aktion an, bevor du sie ausführst. "
        "Beispiel: 'Ich prüfe jetzt die Verfügbarkeit für Sie.' oder 'Ich trage den Termin jetzt ein.'"
        "\n- Frage gezielt und einzeln: erst Datum, dann Uhrzeit, dann Name."
        "\n- Bei technischen Fragen: 'Das klärt unser Spezialist im Termin – kein Problem.'"
        "\n- Niemals Fakten erfinden. Niemals zögern."
        "\n- Wenn ein Termin gebucht ist: Bestätige Datum, Uhrzeit und Name präzise."
        "\n- WICHTIG: Wenn der Kunde das Thema wechselt (z.B. eine Frage stellt statt ein Datum zu nennen), "
        "brich den Buchungsvorgang sofort ab und beantworte die Frage. Rufe KEINE Funktion auf, wenn Informationen fehlen."
    )

    greeting: str = (
        "Begrüße den Kunden knapp und professionell als digitaler Vertriebs-Assistent von Intraunit. "
        "Frage direkt, womit du helfen kannst. Maximal 2 Sätze."
    )


@dataclass(frozen=True)
class ServerConfig:
    health_port: int = field(default_factory=lambda: int(os.getenv("HEALTH_PORT", "8080")))
    host: str = "0.0.0.0"


@dataclass(frozen=True)
class AppConfig:
    google_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""))
    livekit_url: str = field(default_factory=lambda: os.getenv("LIVEKIT_URL", ""))
    mode: str = "DEV"   # wird in main.py gesetzt

    voice: VoiceConfig = field(default_factory=VoiceConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    server: ServerConfig = field(default_factory=ServerConfig)

    def validate(self) -> None:
        """Schlägt früh fehl — nicht mitten im Gespräch."""
        missing = []
        if not self.google_api_key:
            missing.append("GOOGLE_API_KEY")
        if missing:
            raise EnvironmentError(f"Fehlende Umgebungsvariablen: {', '.join(missing)}")


# Singleton — einmal laden, überall nutzen
CONFIG = AppConfig()
