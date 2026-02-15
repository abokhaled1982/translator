"""
patch_livekit.py - Patcht livekit-plugins-google utils.py
Behebt den 1008-Fehler bei Function Calling mit gemini-2.5-flash-native-audio-latest.

Problem: msg.call_id ist None oder leer -> Google wirft 1008
Fix: id nur setzen wenn call_id tatsaechlich vorhanden ist
"""
import sys
import importlib.util
import os

# Finde die utils.py des Plugins
spec = importlib.util.find_spec("livekit.plugins.google")
if not spec:
    print("FEHLER: livekit-plugins-google nicht gefunden!")
    sys.exit(1)

plugin_dir = os.path.dirname(spec.origin)
utils_path = os.path.join(plugin_dir, "utils.py")
print(f"Patche: {utils_path}")

with open(utils_path, "r", encoding="utf-8") as f:
    content = f.read()

# Zeige aktuellen Stand der betroffenen Stelle
print("\n--- Aktueller Code (Zeilen mit call_id / res.id) ---")
for i, line in enumerate(content.splitlines()):
    if "call_id" in line or "res.id" in line:
        print(f"  {i+1:4}: {line}")

# Der Fix: id nur setzen wenn call_id nicht None/leer ist
old = "            if not vertexai:\n                # vertexai does not support id in FunctionResponse\n                # see: https://github.com/googleapis/python-genai/blob/85e00bc/google/genai/_live_converters.py#L1435\n                res.id = msg.call_id"

new = "            if not vertexai:\n                # vertexai does not support id in FunctionResponse\n                # see: https://github.com/googleapis/python-genai/blob/85e00bc/google/genai/_live_converters.py#L1435\n                # Only set id if call_id is present - avoids 1008 with gemini-2.5-flash-native-audio\n                if msg.call_id:\n                    res.id = msg.call_id"

if old in content:
    patched = content.replace(old, new)
    with open(utils_path, "w", encoding="utf-8") as f:
        f.write(patched)
    print("\nPatch erfolgreich angewendet!")
    print("Starte deinen Agent neu.")
else:
    print("\nCode-Block nicht gefunden - pruefen ob bereits gepatcht oder Plugin-Version unterschiedlich.")
    print("\nBitte manuell in utils.py suchen nach 'res.id = msg.call_id' und aendern zu:")
    print("    if msg.call_id:")
    print("        res.id = msg.call_id")
    print(f"\nDatei: {utils_path}")