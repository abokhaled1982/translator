import asyncio
import os
import sys
import pyaudio
from dotenv import load_dotenv
from google import genai

load_dotenv()

# --- KONFIGURATION ---
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000     
RECEIVE_SAMPLE_RATE = 24000  # Gemini Standard
CHUNK_SIZE = 1024

api_key = os.getenv("GOOGLE_API_KEY")

client = genai.Client(
    api_key=api_key,
    http_options={"api_version": "v1alpha"}
)

# Konfiguration ohne verschachtelte generation_config (Vermeidet DeprecationWarning)
# Nutzt Transkription, um Text trotz Audio-Modus zu erhalten
# --- KORRIGIERTE KONFIGURATION ---
CONFIG = {
    "system_instruction": (
        "Du bist ein professioneller Echtzeit-Dolmetscher. "
        "Antworte IMMER laut und deutlich auf Deutsch."
    ),
    "response_modalities": ["AUDIO"],
    "speech_config": {
        "voice_config": {
            "prebuilt_voice_config": {"voice_name": "Puck"}
        }
    },
    # NEU: Muss ein Dictionary sein, kein Boolean
    "output_audio_transcription": {} 
}

pya = pyaudio.PyAudio()

class GeminiLiveInterpreter:
    def __init__(self):
        self.audio_in_queue = asyncio.Queue()
        self.out_queue = asyncio.Queue(maxsize=5)
        self.session = None

    async def listen_mic(self):
        """Ersetzt transport.input()"""
        stream = await asyncio.to_thread(
            pya.open, format=FORMAT, channels=CHANNELS, rate=SEND_SAMPLE_RATE,
            input=True, frames_per_buffer=CHUNK_SIZE
        )
        while True:
            data = await asyncio.to_thread(stream.read, CHUNK_SIZE, exception_on_overflow=False)
            await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})

    async def receive_and_diagnose(self):
        """Ersetzt DiagnosticPrinter() und receive_audio()"""
        while True:
            async for response in self.session.receive():
                # 1. AUDIO DIAGNOSE (🔊 Symbol wie in deinem DiagnosticPrinter)
                if data := response.data:
                    print("🔊", end="", flush=True) 
                    self.audio_in_queue.put_nowait(data)
                
                # 2. TEXT DIAGNOSE (📝 Anzeige wie in deinem DiagnosticPrinter)
                # Text kommt bei Modality AUDIO über server_content.model_turn
                if response.server_content and response.server_content.model_turn:
                    for part in response.server_content.model_turn.parts:
                        if part.text:
                            print(f"\n📝 TEXT EMPFANGEN: {part.text}")

    async def play_audio(self):
        """Ersetzt transport.output()"""
        stream = await asyncio.to_thread(
            pya.open, format=FORMAT, channels=CHANNELS, rate=RECEIVE_SAMPLE_RATE, output=True
        )
        while True:
            bytestream = await self.audio_in_queue.get()
            await asyncio.to_thread(stream.write, bytestream)

    async def send_to_gemini(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send(input=msg)

    async def run(self):
        print("\n--- DIAGNOSE MODUS (Direkt SDK) ---")
        print("Sprich jetzt Arabisch. Achte auf 🔊 und 📝!")
        
        try:
            async with client.aio.live.connect(model="gemini-2.0-flash-exp", config=CONFIG) as session:
                self.session = session
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self.listen_mic())
                    tg.create_task(self.send_to_gemini())
                    tg.create_task(self.receive_and_diagnose())
                    tg.create_task(self.play_audio())
                    await asyncio.Future()
        except Exception as e:
            print(f"\n❌ Fehler: {e}")

if __name__ == "__main__":
    try:
        interpreter = GeminiLiveInterpreter()
        asyncio.run(interpreter.run())
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        pya.terminate()