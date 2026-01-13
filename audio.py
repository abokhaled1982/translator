import asyncio
import os
import sys
import logging
from dotenv import load_dotenv

from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import TextFrame, EndFrame

# Lade Umgebungsvariablen
load_dotenv()

# --- WICHTIG: LOGGING EINSCHALTEN ---
# Damit sehen wir, was im Hintergrund passiert (Fehler, Verbindung, etc.)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.error("KEIN API KEY GEFUNDEN! Bitte überprüfe deine .env Datei.")
        return

    # 1. Audio Transport mit VAD (Spracherkennung)
    # Wir fügen 'SileroVADAnalyzer' hinzu, damit er besser erkennt, wann gesprochen wird.
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_out_enabled=True, # Setze kurz auf True, um zu testen, ob Audio generell geht
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True
        )
    )

    # 2. Gemini Live Service
    llm = GeminiLiveLLMService(
        api_key=api_key,
        model="gemini-2.0-flash-exp",
        system_instruction=(
            "Du bist ein Übersetzer. "
            "Wenn du Arabisch hörst, gib folgendes Format aus: "
            "'AR: [Arabischer Text] | DE: [Deutsche Übersetzung]'. "
            "Antworte nur in diesem Format."
        )
    )

    # 3. Pipeline
    pipeline = Pipeline([
        transport.input(), 
        llm,
        transport.output()
    ])

    # 4. Event Handler für Text
    @llm.event_handler("on_text_frame")
    async def on_text_frame(service, frame: TextFrame):
        # Wir drucken JEDEN Text-Frame, auch leere, um zu sehen ob was ankommt
        print(f"\nEmpfangen: {frame.text}")

    # 5. Task erstellen
    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))
    runner = PipelineRunner()

    print("\n--- DEBUG MODUS GESTARTET ---")
    print("1. Prüfe, ob dein Mikrofon nicht stummgeschaltet ist.")
    print("2. Sprich laut und deutlich Arabisch.")
    print("3. Beobachte die Logs unten...")
    print("-----------------------------\n")

    try:
        await runner.run(task)
    except KeyboardInterrupt:
        print("Beendet.")

if __name__ == "__main__":
    asyncio.run(main())