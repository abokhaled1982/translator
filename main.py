import asyncio
import os
import sys
import logging
from dotenv import load_dotenv

# Pipecat Imports
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.audio.vad.silero import SileroVADAnalyzer

# Google Typen für die Stimmen-Config
from google.genai import types

load_dotenv()

# Logging auf Warning setzen, damit die Konsole sauber bleibt (kein Info-Spam)
logging.basicConfig(level=logging.WARNING, format='%(message)s')

# --- 1. Spezial-Klasse für Native Speaker Audio ---
class NativeGemini(GeminiLiveLLMService):
    def _get_live_config(self):
        return {
            # WICHTIG: Wir fordern explizit nur AUDIO an (kein Text-Ballast)
            "response_modalities": ["AUDIO"],
            
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {
                        # "Fenrir" ist aktuell die tiefste und natürlichste Stimme.
                        # Alternativen: "Kore" (weiblich, klar), "Puck" (Standard)
                        "voice_name": "Fenrir" 
                    }
                }
            }
        }

async def main():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ API Key fehlt!")
        return

    # --- 2. Audio Transport (Deine funktionierenden Settings) ---
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_out_enabled=True,
            vad_enabled=True,             # VAD an = Stoppt wenn du schweigst
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True
        )
    )

    # --- 3. Der "Native Speaker" Prompt ---
    # Dieser Prompt verbietet Roboter-Sprache.
    system_instruction = (
        "Du bist ein professioneller Simultandolmetscher für Arabisch -> Deutsch."
        "Deine Aufgabe: Höre zu und sprich die deutsche Übersetzung sofort aus."
        
        "REGELN FÜR DEINE STIMME:"
        "1. Klinge wie ein echter deutscher Muttersprachler (natürlich, nicht abgelesen)."
        "2. Übersetze den SINN, nicht Wort für Wort. Nutze natürliche Redewendungen."
        "3. Deine Betonung soll lebendig sein."
        "4. Sprich NIEMALS Arabisch. Wiederhole nichts. Nur Deutsch."
    )

    llm = NativeGemini(
        api_key=api_key,
        model="gemini-2.0-flash-exp",
        system_instruction=system_instruction
    )

    # --- 4. Die reine Pipeline (Ohne Printer, ohne Text-Handler) ---
    # Datenfluss: Mikrofon -> Gemini (Audio in, Audio out) -> Kopfhörer
    pipeline = Pipeline([
        transport.input(),
        llm,
        transport.output()
    ])

    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))
    runner = PipelineRunner()

    print("\n============================================")
    print(" 🇩🇪 LIVE DOLMETSCHER (Nur Audio)")
    print("============================================")
    print("System ist bereit. Sprich Arabisch...")
    print("(Die Konsole wird leer bleiben, höre auf den Ton)")
    print("============================================\n")

    try:
        await runner.run(task)
    except KeyboardInterrupt:
        print("Beendet.")

if __name__ == "__main__":
    asyncio.run(main())