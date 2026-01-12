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

# --- SCHUTZ GEGEN HALLUZINATIONEN ---
# Diese Sätze ignoriert das Skript komplett, wenn sie auftauchen
HALLUCINATION_FILTERS = [
    "اشترك في القناة",       # Abonnieren
    "اشتركوا في القناة",     # Abonniert den Kanal
    "شكرا للمشاهدة",         # Danke fürs Zuschauen
    "لا تنسوا الاشتراك",     # Vergesst nicht zu abonnieren
    "تفعيل الجرس",           # Glocke aktivieren
    "Amara.org",             # Untertitel Credits
    "Subtitles by",
    "MBC",                   # TV Sender Rauschen
    "Copyright",
    ".",                     # Einzelne Punkte
    "?"                      # Einzelne Fragezeichen
]

def format_arabic_for_console(text):
    """Hilfsfunktion: Macht Arabisch in der Konsole lesbar"""
    reshaped_text = arabic_reshaper.reshape(text)
    return get_display(reshaped_text)

def normalize_audio(audio_data):
    """
    Audio-Normalisierung MIT Noise Gate.
    Verhindert, dass Stille zu lautem Rauschen verstärkt wird (Ursache für Halluzinationen).
    """
    if np.max(np.abs(audio_data)) == 0:
        return audio_data
        
    audio_float = audio_data.astype(np.float32)
    max_val = np.max(np.abs(audio_float))
    
    # --- NEU: NOISE GATE ---
    # Wenn das Signal extrem leise ist (nur Rauschen), NICHT verstärken!
    # Ein Wert von 500 ist ein guter Schwellenwert für "Stille"
    if max_val < 500: 
        return audio_data # Gib das Original zurück, mach es nicht lauter!
    
    # Wenn Signal laut genug ist, verstärken
    target_level = 31000 
    if max_val < target_level:
        boost_factor = target_level / max_val
        boost_factor = min(boost_factor, 10.0) 
        boosted_audio = audio_float * boost_factor
        return boosted_audio.astype(np.int16)
            
    return audio_data

def is_clean_text(text):
    """Prüft, ob der Text eine bekannte Halluzination ist."""
    if not text or len(text.strip()) < 2:
        return False
        
    # Prüfen ob einer der verbotenen Sätze im Text vorkommt
    for bad_phrase in HALLUCINATION_FILTERS:
        if bad_phrase in text:
            return False
            
    return True

def transcribe_handler(audio: tuple[int, np.ndarray]):
    global last_context
    sample_rate, audio_data = audio
    
    try:
        # 1. Optimieren (Jetzt mit Noise Gate Schutz)
        optimized_audio_data = normalize_audio(audio_data)
        
        # 2. Transkription
        transcript_obj = client.audio.transcriptions.create(
            file=("audio-file.mp3", audio_to_bytes((sample_rate, optimized_audio_data))),
            model="whisper-large-v3-turbo",
            response_format="text",
            language="ar",
            prompt=last_context,
            temperature=0.0 # Temperatur auf 0 zwingt das Modell, präziser zu sein
        )
        
        current_text = transcript_obj.strip()
        
        # 3. FILTER CHECK
        if current_text:
            if is_clean_text(current_text):
                # Nur wenn es KEINE Halluzination ist:
                last_context = (last_context + " " + current_text)[-200:]
                display_text = format_arabic_for_console(current_text)
                logger.success(f"📄 {display_text}")
            else:
                logger.warning(f"👻 Halluzination abgefangen: {format_arabic_for_console(current_text)}")
        
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
    os.system("chcp 65001 > nul") 
    
    logger.info("🚀 ENGINE GESTARTET")
    logger.info("   (Schutz aktiv: Noise Gate & Anti-Youtube-Filter)")
    stream.ui.launch()