import asyncio
import os
import pyaudio
import threading
from google import genai
from google.genai import types
from dotenv import load_dotenv
import arabic_reshaper
from bidi.algorithm import get_display
from colorama import init, Fore, Style

load_dotenv()
init(autoreset=True)

# --- KONFIGURATION ---
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 2048 # Größere Chunks entlasten die CPU

client = genai.Client(http_options={"api_version": "v1alpha"})
MODEL = "gemini-2.0-flash-exp" 
CONFIG = {
    "response_modalities": ["AUDIO"],
    "system_instruction": "Du bist ein Dolmetscher. Übersetze Arabisch sofort ins Deutsche. Antworte NUR auf Deutsch.",
    "input_audio_transcription": {},
}

# Queues und Audio-Instanz
audio_queue_output = asyncio.Queue()
audio_queue_mic = asyncio.Queue(maxsize=20)
pya = pyaudio.PyAudio()

def format_arabic(text):
    if not text: return ""
    return get_display(arabic_reshaper.reshape(text))

# --- MULTITHREADING MIKROFON CALLBACK ---
def mic_callback(in_data, frame_count, time_info, status):
    """Dieser Code läuft in einem eigenen Thread von PyAudio."""
    try:
        # Wir nutzen die Event-Loop des Hauptthreads, um die Daten in die Queue zu schieben
        loop.call_soon_threadsafe(audio_queue_mic.put_nowait, in_data)
    except asyncio.QueueFull:
        pass # Ignorieren, wenn die Queue voll ist
    return (None, pyaudio.paContinue)

async def send_to_gemini(session):
    """Sendet die Daten ohne den Loop zu blockieren."""
    while True:
        audio_chunk = await audio_queue_mic.get()
        try:
            await session.send_realtime_input(
                audio=types.Blob(data=audio_chunk, mime_type='audio/pcm;rate=16000')
            )
            # Ganz wichtig für websockets Stabilität:
            await asyncio.sleep(0) 
        except Exception:
            break

async def receive_from_gemini(session):
    async for msg in session.receive():
        if msg.server_content:
            # 1. Deutsche Audio-Daten
            if msg.server_content.model_turn:
                for part in msg.server_content.model_turn.parts:
                    if part.inline_data:
                        audio_queue_output.put_nowait(part.inline_data.data)
            
            # 2. Arabischer Text
            if msg.server_content.input_transcription:
                ar_text = msg.server_content.input_transcription.text
                if ar_text:
                    print(f"{Fore.CYAN}🇸🇦 ARABISCH: {format_arabic(ar_text)}")

async def play_audio():
    stream = pya.open(format=FORMAT, channels=CHANNELS, rate=RECEIVE_SAMPLE_RATE, output=True)
    while True:
        data = await audio_queue_output.get()
        await asyncio.to_thread(stream.write, data)

async def run():
    global loop
    loop = asyncio.get_running_loop()
    
    while True:
        try:
            # Mikrofon-Stream mit Callback (läuft im Hintergrund-Thread)
            mic_stream = pya.open(
                format=FORMAT, channels=CHANNELS, rate=SEND_SAMPLE_RATE,
                input=True, stream_callback=mic_callback, frames_per_buffer=CHUNK_SIZE
            )
            
            async with client.aio.live.connect(model=MODEL, config=CONFIG) as session:
                print(f"{Fore.GREEN}✅ VERBUNDEN (Multithreaded Mic)!")
                await asyncio.gather(
                    send_to_gemini(session),
                    receive_from_gemini(session),
                    play_audio()
                )
        except Exception as e:
            print(f"{Fore.RED}Fehler: {e}. Neustart...")
            if 'mic_stream' in locals(): mic_stream.stop_stream()
            await asyncio.sleep(2)

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pya.terminate()