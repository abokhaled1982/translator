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

# --- GEDÄCHTNIS (MEMORY) ---
last_context = ""

def format_arabic_for_console(text):
    """Hilfsfunktion: Macht Arabisch in der Konsole lesbar"""
    reshaped_text = arabic_reshaper.reshape(text)
    return get_display(reshaped_text)

def normalize_audio(audio_data):
    """
    NEU: Audio-Normalisierung
    Hebt die Lautstärke auf ein optimales Level an, bevor es zur KI geht.
    Löst Probleme mit leisen Mikrofonen oder großem Abstand.
    """
    # Wenn Audio leer/stumm ist, nichts tun
    if np.max(np.abs(audio_data)) == 0:
        return audio_data
        
    # Konvertieren zu Float für Berechnungen
    audio_float = audio_data.astype(np.float32)
    
    # Den lautesten Punkt im Audio finden
    max_val = np.max(np.abs(audio_float))
    
    # Wenn Signal da ist, verstärken
    if max_val > 0:
        # Ziel: Ca. 95% der maximalen Lautstärke (int16 max ist ~32767)
        target_level = 31000 
        
        # Wenn es schon laut ist, nicht übersteuern, sonst verstärken
        if max_val < target_level:
            boost_factor = target_level / max_val
            # Limiter: Nicht mehr als 10-fach verstärken (verhindert Rausch-Explosion)
            boost_factor = min(boost_factor, 10.0) 
            
            boosted_audio = audio_float * boost_factor
            return boosted_audio.astype(np.int16)
            
    return audio_data

def transcribe_handler(audio: tuple[int, np.ndarray]):
    """
    Verarbeitet Audio: Normalisieren -> Transkribieren -> Kontext merken.
    """
    global last_context
    
    # Audio Tuple entpacken (SampleRate, Daten)
    sample_rate, audio_data = audio
    
    try:
        # 1. OPTIMIERUNG: Audio laut machen
        optimized_audio_data = normalize_audio(audio_data)
        
        # 2. TRANSKRIPTION (Mit optimiertem Audio & Memory-Prompt)
        transcript_obj = client.audio.transcriptions.create(
            # WICHTIG: Hier nutzen wir jetzt das 'optimized_audio_data'
            file=("audio-file.mp3", audio_to_bytes((sample_rate, optimized_audio_data))),
            model="whisper-large-v3-turbo",
            response_format="text",
            language="ar",
            prompt=last_context  # Das Gedächtnis
        )
        
        current_text = transcript_obj.strip()
        
        if current_text:
            # 3. Gedächtnis aktualisieren (letzte ~200 Zeichen)
            last_context = (last_context + " " + current_text)[-200:]
            
            # 4. Anzeige
            display_text = format_arabic_for_console(current_text)
            logger.success(f"📄 {display_text}")
        
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
    # Windows-Terminal auf UTF-8 schalten
    os.system("chcp 65001 > nul") 
    
    logger.info("🚀 AUDIO-BOOST ENGINE GESTARTET")
    logger.info("   (Inkl. Memory & Lautstärke-Optimierung)")
    stream.ui.launch()