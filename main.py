import asyncio
import os
import sys

# --- 1. SYSTEM-LOGGING SÄUBERN ---
# Entfernt alle technischen Debug-Meldungen von Pipecat/HTTP
from loguru import logger as system_logger
system_logger.remove()
system_logger.add(sys.stderr, level="CRITICAL")

# --- 2. BIBLIOTHEKEN LADEN ---
import arabic_reshaper
from bidi.algorithm import get_display
from colorama import Fore, Style, init

from pipecat.frames.frames import TranscriptionFrame, ErrorFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.groq.stt import GroqSTTService
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

# Windows Terminal auf UTF-8 zwingen
init()
if sys.platform == "win32":
    os.system("chcp 65001 >nul")

# -------------------------------------------------------------------------
# HELPER: Arabische Schrift für Terminal fixen
# -------------------------------------------------------------------------
def fix_arabic_text(text):
    """
    Verbindet arabische Buchstaben und dreht die Leserichtung für das Terminal.
    """
    if not text or not text.strip():
        return ""
    try:
        reshaped_text = arabic_reshaper.reshape(text)
        bidi_text = get_display(reshaped_text)
        return bidi_text
    except Exception:
        return text

# -------------------------------------------------------------------------
# LOGGER: Professionelle Ausgabe
# -------------------------------------------------------------------------
class ProductionLogger(FrameProcessor):
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
            if text:
                formatted = fix_arabic_text(text)
                # Ausgabeformat: Grün, Fett, Sauber
                print(f"{Fore.GREEN}{Style.BRIGHT}📝 TEXT:{Style.RESET_ALL} {formatted}")
        
        elif isinstance(frame, ErrorFrame):
            print(f"{Fore.RED}❌ FEHLER: {frame.error}{Style.RESET_ALL}")

# -------------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------------
async def main():
    # 1. API Key Prüfung
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        print(f"{Fore.RED}FEHLER: GROQ_API_KEY fehlt in den Umgebungsvariablen.{Style.RESET_ALL}")
        return

    # 2. UI Header
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"{Fore.YELLOW}=======================================================")
    print(f"   ARABIC TRANSCRIPTION ENGINE (Pro Config)")
    print(f"   Modell: Whisper-Large-v3-Turbo | Modus: Hocharabisch")
    print(f"======================================================={Style.RESET_ALL}\n")

    # 3. VAD (Voice Activity Detection) - Tuning für Produktion
    vad_params = VADParams(
        confidence=0.6,      # Hohe Schwelle: Ignoriert Lüfter/Atmen
        start_secs=0.2,      # Reagiert schnell auf Sprachbeginn
        stop_secs=0.8,       # Wartet 0.8s Stille (Wichtig für arabische Pausen!)
        min_volume=0.0       # Ignoriert Lautstärke, achtet nur auf Sprach-Muster
    )

    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_out_enabled=False, # Kein Lautsprecher nötig (nur Input)
            audio_in_enabled=True,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=vad_params)
        )
    )

    # 4. STT (Groq) - Der Kern für Qualität
    # Dieser Prompt zwingt Whisper in den "Fusha"-Modus
    arabic_system_prompt = "اللغة العربية الفصحى. يرجى الكتابة بدقة لغوية عالية وتجنب الهلوسة. التشكيل عند الضرورة."
    # Bedeutung: "Hocharabisch. Bitte mit hoher sprachlicher Genauigkeit schreiben und Halluzinationen vermeiden."

    stt = GroqSTTService(
        api_key=groq_key,
        model="whisper-large-v3-turbo", # Turbo für max Geschwindigkeit
        language="ar",                  # Sprache festlegen
        prompt=arabic_system_prompt,    # <--- DEIN GEWÜNSCHTER PROMPT
        temperature=0.0                 # <--- WICHTIG: 0.0 verhindert Erfindungen/Halluzinationen
    )

    # 5. Pipeline Aufbau
    logger = ProductionLogger()

    pipeline = Pipeline([
        transport.input(), # Mikrofon
        stt,               # Whisper AI
        logger             # Ausgabe
    ])

    task = PipelineTask(
        pipeline, 
        params=PipelineParams(allow_interruptions=True)
    )

    runner = PipelineRunner()

    print(f"{Fore.CYAN}System bereit. Bitte sprechen... (STRG+C zum Beenden){Style.RESET_ALL}\n")

    try:
        await runner.run(task)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Beendet.{Style.RESET_ALL}")

if __name__ == "__main__":
    asyncio.run(main())