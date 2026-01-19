import logging
import os
import asyncio
import threading
import collections
import numpy as np
import sounddevice as sd
from dotenv import load_dotenv

from livekit import rtc
import livekit.agents as agents
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google, elevenlabs, silero

load_dotenv()
load_dotenv(".env.local")

# Professionelles Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("HighPerfAgent")

# --- KLASSE 1: THREAD-SAFE AUDIO BUFFER (Der "Puffer") ---
class AudioBuffer:
    """
    Ein Thread-sicherer Ring-Buffer.
    Der Async-Loop füllt ihn (Writer), der Audio-Hardware-Thread leert ihn (Reader).
    """
    def __init__(self):
        self.buffer = collections.deque()
        self.lock = threading.Lock()
        self._closed = False

    def write(self, data: np.ndarray):
        """Wird vom Async-Loop aufgerufen."""
        with self.lock:
            if self._closed: return
            # Wir speichern Chunks. np.copy ist wichtig für Thread-Safety.
            self.buffer.append(np.copy(data))

    def read(self, num_samples):
        """Wird vom Soundkarten-Callback (Hardware-Thread) aufgerufen."""
        out_data = []
        samples_needed = num_samples

        with self.lock:
            while samples_needed > 0 and self.buffer:
                chunk = self.buffer[0]
                
                if len(chunk) > samples_needed:
                    # Nimm was wir brauchen, lass den Rest im Buffer
                    part = chunk[:samples_needed]
                    self.buffer[0] = chunk[samples_needed:] # Rest zurücklegen
                    out_data.append(part)
                    samples_needed -= len(part)
                else:
                    # Nimm den ganzen Chunk
                    out_data.append(chunk)
                    samples_needed -= len(chunk)
                    self.buffer.popleft() # Chunk ist leer, weg damit

        if not out_data:
            return np.zeros(num_samples, dtype=np.int16)

        result = np.concatenate(out_data)
        
        # Wenn wir nicht genug Daten hatten (Buffer Underrun), füllen wir mit Stille auf
        if len(result) < num_samples:
            padding = np.zeros(num_samples - len(result), dtype=np.int16)
            result = np.concatenate((result, padding))
            
        return result

    def clear(self):
        with self.lock:
            self.buffer.clear()

# --- KLASSE 2: DER HIGH-PERFORMANCE SPEAKER ---
class HighPerfSpeaker:
    def __init__(self, api_key, voice_id, sample_rate=22050):
        self.tts = elevenlabs.TTS(
            api_key=api_key,
            model="eleven_turbo_v2_5",
            voice_id=voice_id
        )
        self.queue = asyncio.Queue()
        self.audio_buffer = AudioBuffer()
        self.sample_rate = sample_rate
        self.running = True
        
        # LiveKit Audio Track
        self.lk_source = None
        
        # Hardware Stream starten (Non-Blocking Callback Mode)
        try:
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype='int16',
                callback=self._audio_callback,
                blocksize=1024, # Kleine Blocksize für niedrige Latenz
                latency='low'
            )
            self.stream.start()
            logger.info(f"✅ [AUDIO-HW] Stream gestartet @ {self.sample_rate}Hz")
        except Exception as e:
            logger.error(f"❌ [AUDIO-HW] Fehler beim Starten: {e}")
            self.stream = None

    def _audio_callback(self, outdata, frames, time, status):
        """
        Dieser Code läuft in einem separaten C-Thread der Soundkarte!
        Er darf NIEMALS blockieren. Keine Prints, keine API-Calls hier.
        """
        if status:
            # Status kann "Underflow" anzeigen, wenn PC zu langsam ist
            pass 
        
        data = self.audio_buffer.read(frames)
        # Reshape für sounddevice (Frames, Channels)
        outdata[:] = data.reshape(-1, 1)

    async def init_livekit(self, room: rtc.Room):
        self.lk_source = rtc.AudioSource(self.sample_rate, 1)
        track = rtc.LocalAudioTrack.create_audio_track("ai_voice", self.lk_source)
        options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        await room.local_participant.publish_track(track, options)
        logger.info("✅ [LIVEKIT] Audio Track published")

    def speak(self, text: str):
        # Fire and forget -> ab in die Queue
        self.queue.put_nowait(text)

    def interrupt(self):
        """Sofortiges Schweigen."""
        # 1. Queue leeren
        while not self.queue.empty():
            try: self.queue.get_nowait(); self.queue.task_done()
            except: break
        # 2. Audio Buffer leeren (stoppt Sound sofort)
        self.audio_buffer.clear()
        logger.info("🛑 [SPEAKER] Unterbrochen.")

    async def run_loop(self):
        logger.info("🚀 [SPEAKER-LOOP] Bereit für Text...")
        while self.running:
            text = await self.queue.get()
            
            try:
                # API Call (das dauert am längsten)
                audio_stream = self.tts.synthesize(text)
                
                async for audio_frame in audio_stream:
                    # 1. Daten für LiveKit (Remote)
                    if self.lk_source:
                        await self.lk_source.capture_frame(audio_frame.frame)
                    
                    # 2. Daten für Lokale Hardware
                    # Konvertieren in Numpy int16
                    data_np = np.frombuffer(audio_frame.frame.data, dtype=np.int16)
                    
                    # Ab in den Buffer damit (Thread-Safe Push)
                    # Dies blockiert NICHT, es kopiert nur Speicher.
                    self.audio_buffer.write(data_np)
                    
            except Exception as e:
                logger.error(f"❌ Error synthesizing: {e}")
            
            self.queue.task_done()

# --- MAIN AGENT ---
class Assistant(Agent):
    def __init__(self):
        super().__init__(instructions="Du bist ein Dolmetscher.")

async def entrypoint(ctx: agents.JobContext):
    logger.info(f"Verbinde mit Raum: {ctx.room.name}")
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)

    # 1. High Performance Speaker initialisieren
    speaker = HighPerfSpeaker(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        voice_id="JBFqnCBsd6RMkjVDRZzb"
    )
    await speaker.init_livekit(ctx.room)
    
    # Speaker Loop im Hintergrund starten
    asyncio.create_task(speaker.run_loop())

    # 2. Gemini Setup
    llm_model = google.beta.realtime.RealtimeModel(
        model="gemini-2.0-flash-exp",
        api_key=os.getenv("GOOGLE_API_KEY"),
        modalities=["text"],
    )

    # VAD Setup (Präzise eingestellt)
    vad = silero.VAD.load(
        min_silence_duration=0.4,
        min_speech_duration=0.1,
    )

    # Session Setup
    session = AgentSession(llm=llm_model, vad=vad, tts=None)

    @session.on("user_input_transcribed")
    def on_user_input(event):
        # Wenn der User spricht -> Bot sofort unterbrechen
        #speaker.interrupt()
        print(f"🎤 [USER] {event.transcript}")

    @session.on("conversation_item_added")
    def on_item(event):
        item = getattr(event, 'item', event)
        text = ""
        
        if hasattr(item, 'content'):
            if isinstance(item.content, str): text = item.content
            elif isinstance(item.content, list):
                for p in item.content:
                    if isinstance(p, str): text += p
                    elif hasattr(p, 'text'): text += p.text
        
        if text and item.role == "assistant":
            print(f"🤖 [AI] {text}")
            speaker.speak(text)

    print("--- SYSTEM BEREIT ---")
    await session.start(Assistant(), room=ctx.room)
    await asyncio.Event().wait()

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))