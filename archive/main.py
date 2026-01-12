import os
import sys
from dotenv import load_dotenv
from groq import Groq
from fastrtc import Stream, ReplyOnPause, audio_to_bytes
import numpy as np
from loguru import logger

# --- ARABISCH DISPLAY FIX ---
import arabic_reshaper
from bidi.algorithm import get_display

# Konfiguration der Konsole
logger.remove()
logger.add(
    sys.stdout,
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
)

load_dotenv()
client = Groq()

def transcribe_handler(audio: tuple[int, np.ndarray]):
    """Verarbeitet Audio und fixt die arabische Darstellung."""
    try:
        # 1. Transkription
        transcript = client.audio.transcriptions.create(
            file=("audio-file.mp3", audio_to_bytes(audio)),
            model="whisper-large-v3-turbo",
            response_format="text",
            language="ar" # Explizit auf Arabisch stellen für bessere Qualität
        )
        
        if transcript.strip():
            # 2. DER FIX: Buchstaben verbinden & Richtung umkehren
            reshaped_text = arabic_reshaper.reshape(transcript)
            bidi_text = get_display(reshaped_text)
            
            logger.success(f"📄 ERKANNT: {bidi_text}")
        
    except Exception as e:
        logger.error(f"❌ Fehler: {e}")

    if False: yield None

# Stream Konfiguration
stream = Stream(
    modality="audio",
    mode="send",
    handler=ReplyOnPause(transcribe_handler)
)

if __name__ == "__main__":
    # Windows-Terminal auf UTF-8 schalten (dein chcp 65001 Trick)
    os.system("chcp 65001 > nul") 
    
    logger.info("🚀 ARABIC-READY ENGINE GESTARTET")
    stream.ui.launch()