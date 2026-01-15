import pyaudio

p = pyaudio.PyAudio()

print("\n-------------------------------------------")
print("VERFÜGBARE LAUTSPRECHER (OUTPUT DEVICES):")
print("-------------------------------------------")

found = False
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    # Wir suchen nur Geräte mit Ausgangskanälen (Output)
    if info['maxOutputChannels'] > 0:
        print(f"ID: {i}  | Name: {info['name']}")
        found = True

if not found:
    print("❌ Keine Lautsprecher gefunden!")

print("-------------------------------------------\n")
p.terminate()