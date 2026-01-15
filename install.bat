@echo off
setlocal
title Gemini & Pipecat Installer
color 0A

echo ===================================================
echo      SETUP: Google Gemini Live + Pipecat AI
echo ===================================================
echo.

REM --- 1. Python Check ---
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [FEHLER] Python wurde nicht gefunden!
    echo Bitte installiere Python 3.10 oder neuer.
    pause
    exit /b
)

REM --- 2. Virtual Environment (venv) erstellen ---
if not exist "venv" (
    echo [INFO] Erstelle neuen "venv" Ordner...
    python -m venv venv
) else (
    echo [INFO] "venv" bereits vorhanden.
)

REM --- 3. Umgebung aktivieren ---
echo [INFO] Aktiviere venv...
call venv\Scripts\activate.bat

REM --- 4. PIP Update (WICHTIG fuer Wheels) ---
echo [INFO] Aktualisiere pip...
python -m pip install --upgrade pip

REM --- 5. Installationen ---
echo.
echo [INFO] Installiere Google GenAI SDK...
pip install google-genai

echo.
echo [INFO] Installiere Pipecat (mit Google & Silero Plugins)...
REM Anfuehrungszeichen sind wichtig wegen der eckigen Klammern!
pip install "pipecat-ai[google,silero]"

echo.
echo [INFO] Installiere Hilfspakete (Dotenv, Colorama)...
pip install python-dotenv colorama

echo.
echo [INFO] Installiere PyAudio...
REM Wir versuchen erst die Standard-Installation
pip install pyaudio

REM --- 6. Fehler-Check fuer PyAudio ---
if %errorlevel% neq 0 (
    color 0E
    echo.
    echo ============================================================
    echo [WARNUNG] Automatische PyAudio Installation fehlgeschlagen.
    echo Das ist normal auf Windows. Wir versuchen Plan B.
    echo.
    echo Bitte lade das passende "Wheel" herunter und installiere es manuell:
    echo.
    echo 1. Lade herunter: https://github.com/intxcc/pyaudio_portaudio/raw/master/bin/PyAudio-0.2.11-cp310-cp310-win_amd64.whl
    echo 2. Befehl: pip install .\PyAudio-0.2.11-cp310-cp310-win_amd64.whl
    echo ============================================================
) else (
    echo.
    echo [OK] PyAudio erfolgreich installiert.
)

echo.
echo ===================================================
echo      INSTALLATION ABGESCHLOSSEN
echo ===================================================
echo.
echo WICHTIG fuer VS Code:
echo 1. Druecke STRG+SHIFT+P
echo 2. Waehle "Python: Select Interpreter"
echo 3. Waehle "('venv': venv)" aus der Liste!
echo.
echo Starte dein Skript jetzt mit: python test.py
echo.

REM Laesst das Fenster offen und bleibt im VENV
cmd /k