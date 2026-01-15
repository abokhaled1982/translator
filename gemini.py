import asyncio
import os
import sys
import logging
from dotenv import load_dotenv

# Pipecat Core
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.audio.vad.silero import SileroVADAnalyzer

# WICHTIG: Alle Frame-Typen
from pipecat.frames.frames import TextFrame, EndFrame, StartFrame, InputAudioRawFrame

# --- KONFIGURATION & FARBEN ---
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    C_AR = Fore.YELLOW       # Arabisch
    C_DE = Fore.CYAN         # Deutsch
    C_SYS = Fore.LIGHTBLACK_EX
    C_RESET = Style.RESET_ALL
except ImportError:
    C_AR = C_DE = C_SYS = C_RESET = ""

load_dotenv()

# --- DER PROFI LOGGER (Jetzt mit Bugfix) ---
class TranslationLogger(FrameProcessor):
    def __init__(self):
        # HIER WAR DER FEHLER: Wir müssen die Klasse initialisieren!
        super().__init__()
        self._started = False 

    async def queue_frame(self, frame, direction):
        """
        Der 'Türsteher' für die Pipeline.
        Filtert Fehler und Echos heraus.
        """
        
        # 1. StartFrame erkennen und merken, dass es losgeht
        if isinstance(frame, StartFrame):
            self._started = True
            await super().queue_frame(frame, direction)
            return

        # 2. Wenn System noch nicht bereit -> Daten löschen (Verhindert rote Fehler)
        if not self._started:
            return

        # 3. Echo-Killer: Wenn das Audio vom Mikrofon kommt -> Löschen
        if isinstance(frame, InputAudioRawFrame):
            return

        # 4. Text-Verarbeitung (Hübsche Anzeige)
        if isinstance(frame, TextFrame):
            text = frame.text.strip()
            if text:
                if "§" in text:
                    clean = text.replace("[AR]", "").strip()
                    print(f"\n{C_AR}🎤 Arabisch: {clean}{C_RESET}")
                elif "[DE]" in text:
                    clean = text.replace("[DE]", "").strip()
                    print(f"{C_DE}🎧 Deutsch:  {clean}{C_RESET}")
                else:
                    print(f"{C_SYS}{text}{C_RESET}", end="", flush=True)

        # 5. Alles andere (z.B. Audio von Gemini) weiterleiten
        await super().queue_frame(frame, direction)


async def main():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ FEHLER: GOOGLE_API_KEY fehlt.")
        return

    # 1. Audio Transport
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_out_enabled=True, 
            vad_enabled=True,       
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True
        )
    )

    # 2. Gemini Live Konfiguration
    system_prompt = (
        "Du bist ein professioneller Simultan-Dolmetscher."
        "Regeln:"
        "1. Höre auf Arabisch."
        "2. Gib das arabische Transkript als TEXT aus: '...'. NICHT vorlesen."
        "3. Übersetze ins Deutsche: '| ...'.§"
        "4. Sprich (Audio) NUR den deutschen Teil."
    )

    llm = GeminiLiveLLMService(
        api_key=api_key,
        model="gemini-2.0-flash-exp",
        system_instruction=system_prompt,
        voice_id="Puck" 
    )

    # 3. Pipeline
    logger = TranslationLogger()
    
    pipeline = Pipeline([
        transport.input(),
        llm,
        logger,
        transport.output()
    ])

    # 4. Start
    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))
    runner = PipelineRunner()

    print(f"\n{C_DE}=== LIVE DOLMETSCHER (AR -> DE) ==={C_RESET}")
    print(f"{C_SYS}Warte auf Google Verbindung...{C_RESET}")

    try:
        await runner.run(task)
    except KeyboardInterrupt:
        print(f"\n{C_SYS}Beendet.{C_RESET}")
        await task.queue_frame(EndFrame())

if __name__ == "__main__":
    asyncio.run(main())