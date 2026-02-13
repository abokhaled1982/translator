import os
import asyncio
from dotenv import load_dotenv
from google import genai

load_dotenv()
load_dotenv(".env.local")

async def main():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ Kein GOOGLE_API_KEY gefunden!")
        return

    print(f"🔑 Prüfe API Key: {api_key[:5]}...{api_key[-3:]}")
    
    try:
        client = genai.Client(api_key=api_key)
        print("\n📡 Frage verfügbare Modelle ab...")
        
        # Wir suchen speziell nach Modellen, die 'generateContent' oder 'bidi' unterstützen
        count = 0
        for m in client.models.list():
            # Filter: Zeige nur interessante Modelle (2.0 oder flash)
            if "gemini" in m.name and ("flash" in m.name or "2.0" in m.name):
                print(f"  ✅ Gefunden: {m.name}")
                print(f"     - Capabilities: {m.supported_actions}")
                count += 1
        
        if count == 0:
            print("⚠️ Keine passenden Gemini-Modelle gefunden. Dein Key hat evtl. keine Berechtigung.")
            
    except Exception as e:
        print(f"\n❌ FEHLER bei der Abfrage: {e}")
        print("   -> Dies deutet oft auf eine Regions-Sperre (EU/Deutschland) hin.")

if __name__ == "__main__":
    asyncio.run(main())