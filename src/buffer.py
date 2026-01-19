import logging
import os
import asyncio
import numpy as np             # <--- NEU: Für Audio-Daten-Handling
import sounddevice as sd       # <--- NEU: Für lokale Wiedergabe
from dotenv import load_dotenv

from livekit import rtc
import livekit.agents as agents
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google, elevenlabs, silero

load_dotenv()
load_dotenv(".env.local")

logging.basicConfig(level=logging.INFO)

# --- MODUL 1: DER SPEAKER (ElevenLabs + Lokale Lautsprecher) ---
class ElevenLabsSpeaker:
    def __init__(self, api_key, voice_id):
        self.tts = elevenlabs.TTS(
            api_key=api_key,
            model="eleven_turbo_v2_5",
            voice_id=voice_id
        )
        self.queue = asyncio.Queue()
        self._running = True
        
        # <--- NEU: Wir bereiten den lokalen Lautsprecher vor
        # ElevenLabs nutzt meist 22050Hz oder 44100Hz. Wir starten den Stream dynamisch.
        self.local_stream = None 

    async def run(self, room: rtc.Room):
        target_rate = 22050
        target_channels = 1
        
        print(f"🔍 [SPEAKER-INIT] Erstelle AudioSource: {target_rate}Hz, {target_channels} Channel(s)")
        
        self.source = rtc.AudioSource(target_rate, target_channels)
        track = rtc.LocalAudioTrack.create_audio_track("assistant_voice", self.source)
        options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        
        publication = await room.local_participant.publish_track(track, options)
        print(f"✅ [SPEAKER-READY] Track online: {publication.sid}")

        # <--- NEU: Lokalen Audio-Stream öffnen (für PC-Lautsprecher)
        # Wir öffnen einen Output-Stream mit sounddevice
        self.local_stream = sd.OutputStream(
            samplerate=target_rate, 
            channels=target_channels, 
            dtype='int16' # LiveKit nutzt 16-bit Integer
        )
        self.local_stream.start()

        while self._running:
            text = await self.queue.get()
            print(f"📥 [SPEAKER-INPUT] Verarbeite Text: '{text}'")

            try:
                audio_stream = self.tts.synthesize(text)
                
                frames_count = 0
                async for audio_frame in audio_stream:
                    # 1. An LiveKit senden (Server/Internet)
                    await self.source.capture_frame(audio_frame.frame)
                    
                    # 2. <--- NEU: An lokalen Lautsprecher senden
                    # Wir wandeln die rohen Bytes in ein Format um, das der Lautsprecher versteht
                    data_np = np.frombuffer(audio_frame.frame.data, dtype=np.int16)
                    self.local_stream.write(data_np)
                    
                    frames_count += 1
                
                print(f"🔊 [SPEAKER-DONE] {frames_count} Frames abgespielt & gesendet.")
            except Exception as e:
                print(f"❌ [SPEAKER-ERROR] Fehler: {e}")
            
            self.queue.task_done()
        
        # Aufräumen am Ende
        if self.local_stream:
            self.local_stream.stop()
            self.local_stream.close()

    def speak(self, text: str):
        self.queue.put_nowait(text)

# --- MODUL 2: DER AGENT ---
class Assistant(Agent):
    def __init__(self):
        super().__init__(instructions="Du bist ein Dolmetscher Arabisch -> Deutsch.")

async def entrypoint(ctx: agents.JobContext):
    print(f"🚀 [MAIN] Verbinde... Raum-Rate: {ctx.room.name}")
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)

    # Speaker Modul
    speaker = ElevenLabsSpeaker(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        voice_id="JBFqnCBsd6RMkjVDRZzb"
    )
    # Startet den Speaker-Loop im Hintergrund
    asyncio.create_task(speaker.run(ctx.room))

    # Gemini
    llm_model = google.beta.realtime.RealtimeModel(
        model="gemini-2.0-flash-exp",
        api_key=os.getenv("GOOGLE_API_KEY"),
        modalities=["text"]
    )

    session = AgentSession(llm=llm_model, vad=silero.VAD.load(), tts=None)

    @session.on("user_input_transcribed")
    def on_user_input(event):
        print(f"🎤 [USER-STT] {event.transcript}")       
    
    @session.on("conversation_item_added")
    def on_item(event):
        item = getattr(event, 'item', event)
        text = ""
        
        if hasattr(item, 'content'):
            if isinstance(item.content, list):
                for part in item.content:
                    if isinstance(part, str):
                        text += part
                    elif hasattr(part, 'text'):
                        text += part.text
            elif isinstance(item.content, str):
                text = item.content
        
        if text:
            if item.role == "user":
                print(f"\n🎤 INPUT: {text}")
            elif item.role == "assistant":
                print(f"🇩🇪 OUTPUT: {text}")
                # Hier triggern wir unseren Custom Speaker
                speaker.speak(text)
    
    print("🎙️ [SYSTEM] Agent bereit. Bitte sprechen...")
    await session.start(Assistant(), room=ctx.room)
    await asyncio.Event().wait()

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))