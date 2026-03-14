"""
test_calcom.py — Cal.com API Validator & Debugger.

Zeigt exakt was der Voice Agent an Cal.com schickt und was zurückkommt.
Testet: Slots-Abfrage, Buchung, Payload-Validierung.

Usage:
  python test_calcom.py              → Alle Tests
  python test_calcom.py slots        → Nur Slots-Test
  python test_calcom.py book         → Nur Buchungs-Test (dry-run)
  python test_calcom.py book --live  → Echte Buchung erstellen
"""
import sys
import os
import asyncio
import json
import logging
from datetime import date, datetime, timedelta

# ── Pfad-Fix ──────────────────────────────────────────────────────────────────
_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
sys.path.insert(0, _SRC)

from dotenv import load_dotenv
load_dotenv(os.path.join(_SRC, ".env"))

from config import CONFIG

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_calcom")

# ── Farben (Windows Terminal) ─────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _header(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}{RESET}\n")


def _ok(msg: str) -> None:
    print(f"  {GREEN}✓ {msg}{RESET}")


def _fail(msg: str) -> None:
    print(f"  {RED}✗ {msg}{RESET}")


def _info(msg: str) -> None:
    print(f"  {YELLOW}ℹ {msg}{RESET}")


def _dump(label: str, data) -> None:
    """Pretty-print JSON payload."""
    print(f"\n  {BOLD}{label}:{RESET}")
    formatted = json.dumps(data, indent=4, ensure_ascii=False)
    for line in formatted.split("\n"):
        print(f"    {line}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1: Config-Validierung
# ══════════════════════════════════════════════════════════════════════════════
def test_config() -> bool:
    _header("1. CONFIG-VALIDIERUNG")

    cfg = CONFIG.tools
    all_ok = True

    # API Key
    if cfg.calcom_api_key:
        _ok(f"CALCOM_API_KEY = {cfg.calcom_api_key[:15]}...{cfg.calcom_api_key[-4:]}")
    else:
        _fail("CALCOM_API_KEY fehlt!")
        all_ok = False

    # Event Type ID
    if cfg.calcom_event_type_id:
        _ok(f"CALCOM_EVENT_TYPE_ID = {cfg.calcom_event_type_id}")
        try:
            int(cfg.calcom_event_type_id)
            _ok("  → ist numerisch ✓")
        except ValueError:
            _fail("  → MUSS numerisch sein!")
            all_ok = False
    else:
        _fail("CALCOM_EVENT_TYPE_ID fehlt!")
        all_ok = False

    # API URL
    if cfg.calcom_api_url:
        _ok(f"CALCOM_API_URL = {cfg.calcom_api_url}")
        if cfg.calcom_api_url.endswith("/v2"):
            _ok("  → endet mit /v2 ✓")
        else:
            _fail("  → MUSS mit /v2 enden (z.B. https://api.cal.com/v2)")
            all_ok = False
        if "api.cal.com" in cfg.calcom_api_url:
            _ok("  → api.cal.com erkannt ✓")
        elif "cal.com" in cfg.calcom_api_url and "api." not in cfg.calcom_api_url:
            _fail("  → Das ist die Booking-Page, nicht die API! Muss https://api.cal.com/v2 sein")
            all_ok = False
    else:
        _fail("CALCOM_API_URL fehlt!")
        all_ok = False

    return all_ok


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2: Slots-Abfrage (GET /slots/available)
# ══════════════════════════════════════════════════════════════════════════════
async def test_slots() -> bool:
    _header("2. SLOTS-ABFRAGE (GET /slots/available)")

    # Nächsten Werktag finden
    test_date = date.today() + timedelta(days=1)
    while test_date.weekday() >= 5:  # Samstag/Sonntag überspringen
        test_date += timedelta(days=1)

    date_str = test_date.isoformat()
    _info(f"Test-Datum: {date_str} ({test_date.strftime('%A')})")

    cfg = CONFIG.tools
    import httpx

    url = f"{cfg.calcom_api_url}/slots/available"
    params = {
        "startTime": f"{date_str}T00:00:00.000Z",
        "endTime": f"{(test_date + timedelta(days=1)).isoformat()}T00:00:00.000Z",
        "eventTypeId": cfg.calcom_event_type_id,
    }
    headers = {
        "Authorization": f"Bearer {cfg.calcom_api_key}",
        "cal-api-version": "2024-06-14",
        "Content-Type": "application/json",
    }

    _dump("REQUEST → GET", {"url": url, "params": params})

    try:
        async with httpx.AsyncClient(timeout=10, headers=headers) as client:
            resp = await client.get(url, params=params)

        _info(f"HTTP Status: {resp.status_code}")

        if resp.status_code != 200:
            _fail(f"Erwarte 200, bekam {resp.status_code}")
            _dump("RESPONSE (Fehler)", resp.json())
            return False

        data = resp.json()
        _ok("Status 200 OK")

        slots_data = data.get("data", {}).get("slots", {})
        total_slots = sum(len(v) for v in slots_data.values())

        if total_slots > 0:
            _ok(f"{total_slots} Slots gefunden")
            # Zeige Uhrzeiten
            times = []
            for slot_list in slots_data.values():
                for slot in slot_list:
                    t = slot.get("time", "")
                    if t:
                        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                        times.append(dt.strftime("%H:%M"))
            _info(f"Uhrzeiten: {', '.join(sorted(times))}")
        else:
            _info("Keine Slots verfügbar (Kalender voll oder nicht konfiguriert)")

        _dump("RESPONSE (roh)", data)
        return True

    except Exception as e:
        _fail(f"Exception: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3: Buchung (POST /bookings)
# ══════════════════════════════════════════════════════════════════════════════
async def test_booking(live: bool = False) -> bool:
    _header(f"3. BUCHUNG (POST /bookings) — {'🔴 LIVE' if live else '🟡 DRY-RUN'}")

    cfg = CONFIG.tools
    import httpx

    # Nächsten Werktag finden + freien Slot holen
    test_date = date.today() + timedelta(days=1)
    while test_date.weekday() >= 5:
        test_date += timedelta(days=1)
    date_str = test_date.isoformat()

    headers = {
        "Authorization": f"Bearer {cfg.calcom_api_key}",
        "cal-api-version": "2024-06-14",
        "Content-Type": "application/json",
    }

    # Slot suchen
    _info("Suche freien Slot...")
    async with httpx.AsyncClient(timeout=10, headers=headers) as client:
        slot_resp = await client.get(
            f"{cfg.calcom_api_url}/slots/available",
            params={
                "startTime": f"{date_str}T00:00:00.000Z",
                "endTime": f"{(test_date + timedelta(days=1)).isoformat()}T00:00:00.000Z",
                "eventTypeId": cfg.calcom_event_type_id,
            },
        )

    slots_data = slot_resp.json().get("data", {}).get("slots", {})
    all_slots = [s["time"] for sl in slots_data.values() for s in sl if s.get("time")]

    if not all_slots:
        _fail(f"Keine Slots am {date_str} — kann nicht buchen")
        return False

    first_slot = all_slots[0]  # z.B. "2026-03-16T08:00:00.000Z"
    _ok(f"Slot gefunden: {first_slot}")

    # ── Payload wie der Voice Agent ihn baut ──────────────────────────────────
    # Simuliere IntentHandler-Extraktion
    test_name = "Test Debug"
    test_email = "debug@intraunit.de"
    test_time = "8:30"  # Absichtlich einstellig — testet zfill-Fix
    test_topic = "AI Beratung"

    # So baut tools.py den Payload:
    time_str = test_time
    if len(time_str.split(":")[0]) == 1:
        time_str = time_str.zfill(5)
    start_dt = f"{date_str}T{time_str}:00.000Z"

    payload = {
        "eventTypeId": int(cfg.calcom_event_type_id),
        "start": start_dt,
        "responses": {
            "name": test_name,
            "email": test_email,
            "notes": test_topic,
            "location": {"optionValue": "", "value": "integrations:daily"},
        },
        "timeZone": "Europe/Berlin",
        "language": "de",
        "metadata": {
            "source": "voice-agent",
            "topic": test_topic,
        },
    }

    url = f"{cfg.calcom_api_url}/bookings"

    _dump("REQUEST → POST", {"url": url, "payload": payload})

    # ── Validierung ───────────────────────────────────────────────────────────
    _info("Payload-Validierung:")

    # eventTypeId
    eid = payload["eventTypeId"]
    if isinstance(eid, int) and eid > 0:
        _ok(f"eventTypeId = {eid} (int ✓)")
    else:
        _fail(f"eventTypeId = {eid} (MUSS int > 0 sein!)")

    # start - ISO Format
    start = payload["start"]
    if "T" in start and start.endswith("Z"):
        _ok(f"start = {start} (ISO 8601 ✓)")
    else:
        _fail(f"start = {start} (MUSS ISO 8601 mit Z sein!)")

    # start - Stunde 2-stellig?
    hour_part = start.split("T")[1][:2]
    if hour_part[0].isdigit() and hour_part[1].isdigit():
        _ok(f"Stunde 2-stellig: '{hour_part}' ✓")
    else:
        _fail(f"Stunde: '{hour_part}' — MUSS 2-stellig sein!")

    # Responses
    resp_data = payload["responses"]
    if resp_data.get("name"):
        _ok(f"name = '{resp_data['name']}' ✓")
    else:
        _fail("name fehlt!")

    if resp_data.get("email") and "@" in resp_data["email"]:
        _ok(f"email = '{resp_data['email']}' ✓")
    else:
        _fail(f"email = '{resp_data.get('email')}' — ungültig!")

    # timeZone
    if payload.get("timeZone") == "Europe/Berlin":
        _ok("timeZone = Europe/Berlin ✓")
    else:
        _fail(f"timeZone = {payload.get('timeZone')}")

    # ── zfill-Test ────────────────────────────────────────────────────────────
    _info("")
    _info("zfill-Fix Test (einstellige Stunde):")
    for t_in, t_expect in [("8:30","08:30"), ("9:00","09:00"), ("14:00","14:00"), ("0:30","00:30")]:
        t_out = t_in.zfill(5) if len(t_in.split(":")[0]) == 1 else t_in
        if t_out == t_expect:
            _ok(f"  '{t_in}' → '{t_out}' ✓")
        else:
            _fail(f"  '{t_in}' → '{t_out}' (erwartet '{t_expect}')")

    # ── Live-Buchung ──────────────────────────────────────────────────────────
    if not live:
        _info("")
        _info("DRY-RUN — keine echte Buchung. Nutze 'python test_calcom.py book --live' für echte Buchung.")
        return True

    # Für Live nutzen wir den echten ersten verfügbaren Slot
    payload["start"] = first_slot
    _info(f"LIVE-Buchung mit Slot: {first_slot}")
    _dump("LIVE REQUEST → POST", {"url": url, "payload": payload})

    try:
        async with httpx.AsyncClient(timeout=10, headers=headers) as client:
            resp = await client.post(url, json=payload)

        _info(f"HTTP Status: {resp.status_code}")
        data = resp.json()
        _dump("RESPONSE", data)

        if resp.status_code == 201:
            b = data.get("data", {})
            _ok(f"Buchung erstellt!")
            _ok(f"  ID:     {b.get('id')}")
            _ok(f"  UID:    {b.get('uid')}")
            _ok(f"  Start:  {b.get('startTime')}")
            _ok(f"  Ende:   {b.get('endTime')}")
            _ok(f"  Status: {b.get('status')}")
            _ok(f"  Video:  {b.get('videoCallUrl')}")
            return True
        else:
            _fail(f"Buchung fehlgeschlagen: {resp.status_code}")
            return False

    except Exception as e:
        _fail(f"Exception: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4: IntentHandler Regex-Test
# ══════════════════════════════════════════════════════════════════════════════
def test_regex() -> bool:
    _header("4. INTENT-HANDLER REGEX-TEST")

    from intent_handler import _RE_CHECK_AVAIL, _RE_CHECK_AVAIL_ISO, _RE_BOOK, _RE_END_CALL

    all_ok = True

    # ── Availability Patterns ─────────────────────────────────────────────────
    _info("Availability-Regex:")
    avail_cases = [
        ("Ich schaue kurz im Kalender nach fuer den 17.03.2026", True, "17", "03", "2026"),
        ("Ich schaue kurz im Kalender nach fuer den 5.7.2027", True, "5", "7", "2027"),
        ("Ich prüfe die Verfügbarkeit für den 01.04.2026", True, "01", "04", "2026"),
        ("Check Termin 22-12-2026", True, "22", "12", "2026"),
        ("Hallo wie gehts", False, None, None, None),
    ]
    for text, should_match, exp_d, exp_m, exp_y in avail_cases:
        m = _RE_CHECK_AVAIL.search(text)
        matched = m is not None
        if matched == should_match:
            if matched:
                _ok(f"'{text[:50]}' → Tag={m.group(1)} Mon={m.group(2)} Jahr={m.group(3)}")
                if m.group(1) != exp_d or m.group(2) != exp_m or m.group(3) != exp_y:
                    _fail(f"  Erwartet: Tag={exp_d} Mon={exp_m} Jahr={exp_y}")
                    all_ok = False
            else:
                _ok(f"'{text[:50]}' → kein Match ✓")
        else:
            _fail(f"'{text[:50]}' → {'Match' if matched else 'kein Match'} (erwartet {'Match' if should_match else 'kein Match'})")
            all_ok = False

    # ── Booking Patterns ──────────────────────────────────────────────────────
    _info("")
    _info("Booking-Regex:")
    book_cases = [
        (
            "Ich trage den Termin ein fuer Max Mueller, max@mail.de, am 17.03.2026 um 14:00, Thema AI Beratung.",
            True, "Max Mueller", "max@mail.de", "17", "03", "2026", "14:00", "AI Beratung",
        ),
        (
            "Ich buche den Termin ein fuer Ahmad Ali, info@intraunit.de, am 5.7.2027 um 8:30.",
            True, "Ahmad Ali", "info@intraunit.de", "5", "7", "2027", "8:30", None,
        ),
        (
            "Hallo, ich möchte stornieren",
            False, None, None, None, None, None, None, None,
        ),
    ]
    for text, should_match, *expected in book_cases:
        m = _RE_BOOK.search(text)
        matched = m is not None
        if matched == should_match:
            if matched:
                name, email = m.group(1).strip(), m.group(2).strip()
                day, month, year = m.group(3), m.group(4), m.group(5)
                time_str = m.group(6).strip()
                topic = (m.group(7) or "").strip() or None
                exp_name, exp_email, exp_d, exp_m, exp_y, exp_t, exp_topic = expected
                _ok(f"'{text[:60]}...'")
                _info(f"    Name={name}, Email={email}, Datum={day}.{month}.{year}, Zeit={time_str}, Thema={topic}")

                # Prüfe Einzelwerte
                checks = [
                    (name, exp_name, "Name"),
                    (email, exp_email, "Email"),
                    (day, exp_d, "Tag"),
                    (month, exp_m, "Monat"),
                    (year, exp_y, "Jahr"),
                    (time_str, exp_t, "Zeit"),
                ]
                for got, want, label in checks:
                    if got != want:
                        _fail(f"    {label}: '{got}' != '{want}'")
                        all_ok = False
            else:
                _ok(f"'{text[:50]}' → kein Match ✓")
        else:
            _fail(f"'{text[:60]}' → {'Match' if matched else 'kein Match'} (erwartet {'Match' if should_match else 'kein Match'})")
            all_ok = False

    # ── End Call ──────────────────────────────────────────────────────────────
    _info("")
    _info("End-Call-Regex:")
    for text, should_match in [
        ("Auf Wiedersehen!", True),
        ("Tschüss, bis bald!", True),
        ("Tschuess!", True),
        ("Goodbye!", True),
        ("Ich melde mich", False),
    ]:
        matched = _RE_END_CALL.search(text) is not None
        if matched == should_match:
            _ok(f"'{text}' → {'Match' if matched else 'kein Match'} ✓")
        else:
            _fail(f"'{text}' → {'Match' if matched else 'kein Match'}")
            all_ok = False

    return all_ok


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
async def main():
    args = [a.lower() for a in sys.argv[1:]]
    live = "--live" in args

    print(f"\n{BOLD}╔════════════════════════════════════════════════════════════╗")
    print(f"║  Cal.com API Validator & Debugger                          ║")
    print(f"║  Voice Agent → Cal.com Payload Inspector                   ║")
    print(f"╚════════════════════════════════════════════════════════════╝{RESET}")

    results = {}

    if not args or "config" in args or "all" in args:
        results["Config"] = test_config()

    if not args or "regex" in args or "all" in args:
        results["Regex"] = test_regex()

    if not args or "slots" in args or "all" in args:
        results["Slots"] = await test_slots()

    if not args or "book" in args or "all" in args:
        results["Booking"] = await test_booking(live=live)

    # ── Summary ───────────────────────────────────────────────────────────────
    _header("ZUSAMMENFASSUNG")
    for name, ok in results.items():
        if ok:
            _ok(f"{name}")
        else:
            _fail(f"{name}")

    total_ok = all(results.values())
    print()
    if total_ok:
        print(f"  {GREEN}{BOLD}✓ Alle Tests bestanden!{RESET}")
    else:
        print(f"  {RED}{BOLD}✗ Fehler gefunden — siehe oben{RESET}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
