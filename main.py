import asyncio
import os
import pyaudio
from dotenv import load_dotenv
from google import genai

load_dotenv()

# --- KONFIGURATION ---
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000 
CHUNK_SIZE = 1024

api_key = os.getenv("GOOGLE_API_KEY")

client = genai.Client(
    api_key=api_key,
    http_options={"api_version": "v1alpha"}
)

# Nur Text-Antworten anfordern
CONFIG = {
    "system_instruction": (
        "Du bist ein professioneller Echtzeit-Dolmetscher. "
        "Antworte IMMER nur mit Text auf Deutsch."
    ),
    "response_modalities": ["TEXT"]
}

pya = pyaudio.PyAudio()

class GeminiLiveTextOnly:
    def __init__(self):
        self.out_queue = asyncio.Queue(maxsize=5)
        self.session = None

    async def listen_mic(self):
        """Liest Audio vom Mikrofon und sendet es an die Queue"""
        stream = await asyncio.to_thread(
            pya.open, format=FORMAT, channels=CHANNELS, rate=SEND_SAMPLE_RATE,
            input=True, frames_per_buffer=CHUNK_SIZE
        )
        print("🎤 Mikrofon aktiv - Du kannst jetzt sprechen...")
        while True:
            data = await asyncio.to_thread(stream.read, CHUNK_SIZE, exception_on_overflow=False)
            await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})

    async def receive_text(self):
        """Empfängt nur die Text-Antworten von Gemini"""
        while True:
            async for response in self.session.receive():
                if response.server_content and response.server_content.model_turn:
                    for part in response.server_content.model_turn.parts:
                        if part.text:
                            print(f"🤖 Gemini: {part.text}")

    async def send_to_gemini(self):
        """Sendet Audio-Daten aus der Queue an Gemini"""
        while True:
            msg = await self.out_queue.get()
            await self.session.send(input=msg)

    async def run(self):
        print("\n--- TEXT-ONLY MODUS ---")
        
        try:
            async with client.aio.live.connect(model="gemini-2.0-flash-exp", config=CONFIG) as session:
                self.session = session
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self.listen_mic())
                    tg.create_task(self.send_to_gemini())
                    tg.create_task(self.receive_text())
                    await asyncio.Future()
        except Exception as e:
            print(f"\n❌ Fehler: {e}")

if __name__ == "__main__":
    try:
        interpreter = GeminiLiveTextOnly()
        asyncio.run(interpreter.run())
    except KeyboardInterrupt:
        print("\nProgramm beendet.")
    finally:
        pya.terminate()