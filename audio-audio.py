import asyncio
import os
import sys
import traceback
import pyaudio
from dotenv import load_dotenv # NEU
from google import genai
from google.genai.types import LiveConnectConfig, HttpOptions, Modality

# Lade Umgebungsvariablen aus .env
load_dotenv()

# Check Python Version
if sys.version_info < (3, 11, 0):
    print("Error: This script requires Python 3.11 or newer.")
    sys.exit(1)

# Audio Konfiguration
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000     
RECEIVE_SAMPLE_RATE = 24000  
CHUNK_SIZE = 1024

# --- KONFIGURATION FÜR AI STUDIO (GOOGLE_API_KEY) ---
use_vertexai = False 
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("Error: GOOGLE_API_KEY nicht in der .env Datei gefunden!")
    sys.exit(1)

# Client Initialisierung
client = genai.Client(
    api_key=api_key,
    http_options={"api_version": "v1alpha"}
)

MODEL = "gemini-2.0-flash-exp"
CONFIG = {"generation_config": {"response_modalities": ["AUDIO"]}}

pya = pyaudio.PyAudio()

class AudioLoop:
    def __init__(self):
        self.audio_in_queue = None
        self.out_queue = None
        self.session = None
        self.audio_stream = None
    
    async def listen_audio(self):
        mic_info = pya.get_default_input_device_info()
        self.audio_stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT, 
            channels=CHANNELS, 
            rate=SEND_SAMPLE_RATE,
            input=True, 
            input_device_index=mic_info["index"],
            frames_per_buffer=CHUNK_SIZE,
        )
        
        while True:
            data = await asyncio.to_thread(self.audio_stream.read, CHUNK_SIZE, exception_on_overflow=False)
            await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})
    
    async def receive_audio(self):
        while True:
            # turn ist ein async iterator
            async for response in self.session.receive():
                if data := response.data:
                    self.audio_in_queue.put_nowait(data)
                if text := response.text:
                    print(f"\rGemini: {text}", end="")
            print() 

    async def play_audio(self):
        stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT, 
            channels=CHANNELS, 
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
        )
        while True:
            bytestream = await self.audio_in_queue.get()
            await asyncio.to_thread(stream.write, bytestream)
    
    async def send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send(input=msg)
    
    async def run(self):
        try:
            # Verbindung zum Live-Modus
            async with client.aio.live.connect(model=MODEL, config=CONFIG) as session:
                self.session = session
                self.audio_in_queue = asyncio.Queue()
                self.out_queue = asyncio.Queue(maxsize=5)
                
                print("\n--- Voice Chat gestartet ---")
                print("Sprich jetzt in dein Mikrofon. Beenden mit Strg+C.")
                
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self.send_realtime())
                    tg.create_task(self.listen_audio())
                    tg.create_task(self.receive_audio())
                    tg.create_task(self.play_audio())
                    
                    await asyncio.Future() 
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"\nFehler aufgetreten: {e}")
            traceback.print_exc()
        finally:
            if self.audio_stream:
                self.audio_stream.stop_stream()
                self.audio_stream.close()
            print("\nSession beendet.")

if __name__ == "__main__":
    try:
        main = AudioLoop()
        asyncio.run(main.run())
    except KeyboardInterrupt:
        print("\nAbbruch durch Benutzer.")
    finally:
        pya.terminate()