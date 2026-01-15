import asyncio
import os
import sys
from dotenv import load_dotenv

# Pipecat Imports
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import TextFrame, EndFrame, StartFrame, InputAudioRawFrame

# Design Imports (Wichtig: Group und Rule für die Kombi-Box)
from rich.console import Console
from rich.panel import Panel
from rich.align import Align
from rich.console import Group
from rich.text import Text
from rich.rule import Rule
import arabic_reshaper
from bidi.algorithm import get_display

load_dotenv()
console = Console()

class SingleBoxLogger(FrameProcessor):
    def __init__(self):
        super().__init__()
        self._buffer = "" 
        self._cached_arabic = None # Hier speichern wir Arabisch kurz zwischen

    def _fix_arabic(self, text):
        if not text: return ""
        try:
            return get_display(arabic_reshaper.reshape(text.strip()))
        except:
            return text

    async def queue_frame(self, frame, direction):
        
        # 1. Start: Alles zurücksetzen
        if isinstance(frame, StartFrame):
            self._buffer = ""
            self._cached_arabic = None
            await super().queue_frame(frame, direction)

        # 2. Text verarbeiten
        elif isinstance(frame, TextFrame):
            self._buffer += frame.text

            # Wir nutzen wieder die einfache "Neue Zeile" (\n) Logik
            if "\n" in self._buffer:
                lines = self._buffer.split("\n")

                # Verarbeite alle fertigen Zeilen (alles außer der letzten)
                for line in lines[:-1]:
                    line = line.strip()
                    if not line: continue

                    # FALL A: Arabische Zeile gefunden
                    if line.startswith("AR:"):
                        # Speichern, aber NOCH NICHT drucken!
                        self._cached_arabic = line.replace("AR:", "").strip()
                    
                    # FALL B: Deutsche Zeile gefunden
                    elif line.startswith("DE:"):
                        german_text = line.replace("DE:", "").strip()
                        
                        # Jetzt haben wir beides? Dann DRUCKEN!
                        if self._cached_arabic:
                            
                            # 1. Arabisch schön machen (Rechtsbündig, Gelb)
                            ar_render = Align.right(Text(self._fix_arabic(self._cached_arabic), style="bold yellow"))
                            
                            # 2. Deutsch schön machen (Linksbündig, Cyan)
                            de_render = Align.left(Text(german_text, style="bold cyan"))
                            
                            # 3. Zusammenpacken in eine Gruppe mit Trennlinie
                            content = Group(
                                ar_render,
                                Rule(style="white dim"), # Eine feine Linie dazwischen
                                de_render
                            )
                            
                            # 4. Die EINE Box ausgeben
                            console.print(Panel(content, border_style="green", title="Live Übersetzung"))
                            
                            # Speicher leeren für den nächsten Satz
                            self._cached_arabic = None

                # Puffer aufräumen (letzter Teil bleibt drin)
                self._buffer = lines[-1]

        # 3. Ende
        elif isinstance(frame, EndFrame):
            # Falls noch was übrig ist (selten, aber sicher ist sicher)
            self._buffer = ""
            self._cached_arabic = None
            await super().queue_frame(frame, direction)

        elif isinstance(frame, InputAudioRawFrame):
            pass
        else:
            await super().queue_frame(frame, direction)


async def main():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ API Key fehlt!")
        return

    # Transport
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_out_enabled=True, 
            vad_enabled=True,       
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True
        )
    )

    # PROMPT: Nutze Zeilenumbrüche (AR: ... \n DE: ...)
    system_instruction = (
        "Du bist Dolmetscher."
        "Regel: Nutze für jede Sprache eine NEUE ZEILE."
        "Format:"
        "AR: <Arabischer Text>"
        "DE: <Deutsche Übersetzung>"
        "Wichtig: Immer erst AR, dann DE."
    )

    llm = GeminiLiveLLMService(
        api_key=api_key,
        model="gemini-2.0-flash-exp",
        system_instruction=system_instruction,
        voice_id="Puck"
    )

    pipeline = Pipeline([
        transport.input(),
        llm,
        SingleBoxLogger(), # Der neue Logger
        transport.output()
    ])

    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))
    runner = PipelineRunner()

    console.print(Panel("[bold green]Bereit.[/bold green] Arabisch und Deutsch in EINER Box.", border_style="green"))

    try:
        await runner.run(task)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    asyncio.run(main())
    