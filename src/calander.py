import smtplib
from email.message import EmailMessage
from icalendar import Calendar, Event, vCalAddress, vText
import datetime
import uuid

# ==========================================
# 1. KONFIGURATION (Hier deine Daten rein!)
# ==========================================
ABSENDER_EMAIL = "alghobariwaled@gmail.com"  # Deine E-Mail, von der gesendet wird
ABSENDER_PASSWORT ="yzpt ouyr mgvs xydc"
SMTP_SERVER = "smtp.gmail.com"            # Für Gmail (bei anderen Providern anpassen)
SMTP_PORT = 587

KUNDEN_EMAIL = "whsg@hotmail.de"          # Die E-Mail des Kunden


# ==========================================
# 2. DEN TERMIN ERSTELLEN (.ics Datei)
# ==========================================
def erstelle_ics(titel, startzeit, endzeit, beschreibung, ort):
    cal = Calendar()
    cal.add('prodid', '-//Mein Voice Agent//Terminbuchung//DE')
    cal.add('version', '2.0')
    cal.add('method', 'REQUEST') # Wichtig: Zeigt dem Mail-Programm, dass es eine Einladung ist

    event = Event()
    event.add('summary', titel)
    event.add('dtstart', startzeit)
    event.add('dtend', endzeit)
    event.add('dtstamp', datetime.datetime.now(datetime.timezone.utc))
    event.add('description', beschreibung)
    event.add('location', ort)
    event.add('uid', str(uuid.uuid4()) + '@mein-voice-agent.com') # Jeder Termin braucht eine einmalige ID

    # Organisator (Du) und Teilnehmer (Kunde) hinzufügen
    organizer = vCalAddress(f"MAILTO:{ABSENDER_EMAIL}")
    organizer.params['cn'] = vText("Mein Voice Agent")
    event['organizer'] = organizer

    attendee = vCalAddress(f"MAILTO:{KUNDEN_EMAIL}")
    attendee.params['ROLE'] = vText('REQ-PARTICIPANT')
    attendee.params['RSVP'] = vText('TRUE') # Aktiviert den Zusagen/Absagen Button
    event.add('attendee', attendee, encode=0)

    cal.add_component(event)
    return cal.to_ical()


# ==========================================
# 3. DIE E-MAIL VERSCHICKEN
# ==========================================
def sende_termin_email():
    # Termin-Daten festlegen
    start = datetime.datetime(2025, 6, 15, 10, 0, tzinfo=datetime.timezone.utc)
    ende = datetime.datetime(2025, 6, 15, 11, 0, tzinfo=datetime.timezone.utc)
    
    # ICS-Datei generieren
    ics_daten = erstelle_ics(
        titel="Beratungsgespräch",
        startzeit=start,
        endzeit=ende,
        beschreibung="Hier sind die Details für unser Gespräch.",
        ort="Online / Telefon"
    )

    # E-Mail zusammenbauen
    msg = EmailMessage()
    msg['Subject'] = "Einladung: Beratungsgespräch"
    msg['From'] = ABSENDER_EMAIL
    msg['To'] = KUNDEN_EMAIL
    msg.set_content("Hallo!\n\nAnbei findest du die Termineinladung. Bitte klicke auf 'Zusagen', um den Termin in deinen Kalender zu übernehmen.\n\nLiebe Grüße!")

    # Die ICS-Datei anheften!
    msg.add_attachment(
        ics_daten,
        maintype='text',
        subtype='calendar',
        filename='einladung.ics',
        params={'method': 'REQUEST'}
    )

    # Über SMTP absenden
    try:
        print("Verbinde mit E-Mail-Server...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls() # Verschlüsselung aktivieren
        server.login(ABSENDER_EMAIL, ABSENDER_PASSWORT)
        server.send_message(msg)
        server.quit()
        print(f"✅ Termin-Einladung erfolgreich an {KUNDEN_EMAIL} gesendet!")
    except Exception as e:
        print(f"❌ Fehler beim Senden: {e}")

# Programm starten
if __name__ == "__main__":
    sende_termin_email()