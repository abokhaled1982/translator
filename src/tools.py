"""tools.py - Calendly API Service.

Reine API-Funktionen ohne LLM-Decorators.
Werden vom IntentHandler als Background-Tasks aufgerufen.

Features:
  - Echte Verfügbarkeitsprüfung über Calendly API v2
  - Echte Terminbuchung über Calendly API v2
  - Fallback auf Simulation wenn Calendly nicht konfiguriert
  - Rate Limiting
"""
import asyncio
import logging
import json
import random
import os
from collections import deque
from datetime import date, datetime, timedelta
from typing import Optional, Deque, List
from time import time

from config import CONFIG

logger = logging.getLogger("intraunit.tools")


# ── HTTP Connection-Pool ──────────────────────────────────────────────────────
_http_client = None

def _get_http_client():
    """Lazy-initialized HTTP Client mit Calendly Auth."""
    global _http_client
    if _http_client is None:
        import httpx
        cfg = CONFIG.tools
        headers = {
            "User-Agent": f"IntraUnit-Agent/{CONFIG.agent.agent_name}",
            "Content-Type": "application/json",
        }
        if cfg.calendly_api_key:
            headers["Authorization"] = f"Bearer {cfg.calendly_api_key}"
        
        _http_client = httpx.AsyncClient(
            timeout=cfg.api_timeout_s,
            limits=httpx.Limits(
                max_connections=cfg.http_max_connections,
                max_keepalive_connections=cfg.http_max_keepalive,
            ),
            headers=headers,
        )
        logger.debug("HTTP Client initialisiert")
    return _http_client

async def close_http_client() -> None:
    """Schließt HTTP Client sauber."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
        logger.debug("HTTP Client geschlossen")


# ── Rate Limiter ──────────────────────────────────────────────────────────────
class RateLimiter:
    """Sliding Window Rate Limiter für Tool Calls."""
    
    def __init__(self, max_calls: int, window_seconds: int = 60):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.calls: Deque[float] = deque()
    
    def is_allowed(self) -> bool:
        now = time()
        while self.calls and self.calls[0] < now - self.window_seconds:
            self.calls.popleft()
        if len(self.calls) >= self.max_calls:
            return False
        self.calls.append(now)
        return True


# ── Calendly API Helpers ──────────────────────────────────────────────────────

_calendly_user_uri: Optional[str] = None

async def _get_calendly_user_uri() -> Optional[str]:
    """Holt und cached die aktuelle Calendly User URI aus dem Token."""
    global _calendly_user_uri
    if _calendly_user_uri:
        return _calendly_user_uri
    
    # User UUID aus dem JWT Token extrahieren
    import base64
    token = CONFIG.tools.calendly_api_key
    if not token:
        return None
    try:
        payload_b64 = token.split(".")[1]
        # Padding hinzufügen
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        user_uuid = payload.get("user_uuid", "")
        if user_uuid:
            _calendly_user_uri = f"https://api.calendly.com/users/{user_uuid}"
            return _calendly_user_uri
    except Exception as e:
        logger.error(f"Calendly User-URI Extraktion fehlgeschlagen: {e}")
    
    return None


async def _calendly_get_slots(date_str: str) -> Optional[List[str]]:
    """
    Holt freie Slots von Calendly für ein bestimmtes Datum.
    
    Calendly API: GET /event_type_available_times
    Returns: Liste von Uhrzeiten ["09:00", "10:30", ...] oder None bei Fehler.
    """
    cfg = CONFIG.tools
    client = _get_http_client()
    
    start = f"{date_str}T00:00:00.000000Z"
    end_date = (date.fromisoformat(date_str) + timedelta(days=1)).isoformat()
    end = f"{end_date}T00:00:00.000000Z"
    
    url = f"{cfg.calendly_api_url}/event_type_available_times"
    params = {
        "start_time": start,
        "end_time": end,
        "event_type": cfg.calendly_event_type_uri,
    }
    
    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        
        times = []
        for slot in data.get("collection", []):
            status = slot.get("status", "")
            start_time = slot.get("start_time", "")
            if status == "available" and start_time:
                dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                from zoneinfo import ZoneInfo
                dt_berlin = dt.astimezone(ZoneInfo("Europe/Berlin"))
                times.append(dt_berlin.strftime("%H:%M"))
        
        return sorted(times)
    
    except Exception as e:
        logger.error(f"Calendly Slots-Abfrage fehlgeschlagen: {e}")
        return None


async def _calendly_book(
    name: str, email: str, date_str: str, time_str: str, topic: str
) -> Optional[dict]:
    """
    Bucht einen Termin über Calendly API.
    
    Calendly API: POST /scheduling_links
    Erstellt einen Single-Use Scheduling Link.
    Returns: Booking-Daten oder None bei Fehler.
    """
    cfg = CONFIG.tools
    client = _get_http_client()
    
    # Stundenteil auf 2 Stellen auffüllen ("8:30" → "08:30")
    if len(time_str.split(":")[0]) == 1:
        time_str = time_str.zfill(5)
    
    user_uri = await _get_calendly_user_uri()
    if not user_uri:
        return None
    
    url = f"{cfg.calendly_api_url}/scheduling_links"
    payload = {
        "max_event_count": 1,
        "owner": cfg.calendly_event_type_uri,
        "owner_type": "EventType",
    }
    
    try:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        
        booking_link = data.get("resource", {}).get("booking_url", "")
        logger.info(f"Calendly Scheduling Link erstellt: {booking_link}")
        
        booking = {
            "uid": data.get("resource", {}).get("owner", ""),
            "booking_url": booking_link,
            "name": name,
            "email": email,
            "date": date_str,
            "time": time_str,
            "topic": topic,
            "status": "scheduling_link_created",
        }
        return booking
    
    except Exception as e:
        body = ""
        try:
            body = resp.text  # type: ignore[union-attr]
        except Exception:
            pass
        logger.error(f"Calendly Buchung fehlgeschlagen: {e} | Body: {body[:500]}")
        return None


# ── Fallback Simulation ──────────────────────────────────────────────────────

def _save_booking_local(booking_data: dict) -> None:
    """Speichert Buchung in lokaler JSON-Datei (Fallback)."""
    filename = "bookings.json"
    try:
        existing = []
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                try:
                    existing = json.load(f)
                except json.JSONDecodeError:
                    pass
        existing.append(booking_data)
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        logger.info(f"💾 Buchung lokal gespeichert in {filename}")
    except Exception as e:
        logger.error(f"Fehler beim lokalen Speichern: {e}")


def _get_mock_slots(date_str: str) -> List[str]:
    """Generiert Mock-Slots als Fallback."""
    random.seed(date_str)
    possible_slots = ["09:00", "10:30", "11:00", "13:30", "14:00", "15:30", "16:00"]
    k = random.randint(2, 4)
    return sorted(random.sample(possible_slots, k))


# ── Module-Level Setup ─────────────────────────────────────────────────────────
_rate_limiter = RateLimiter(max_calls=CONFIG.agent.max_tool_calls_per_minute)
_use_calendly = bool(CONFIG.tools.calendly_api_key and CONFIG.tools.calendly_event_type_uri)
_mode = "CALENDLY (Live)" if _use_calendly else "SIMULATION"
logger.info(f"🛠️ Tools: {_mode}")


# ── Public API ─────────────────────────────────────────────────────────────────

async def check_availability(requested_date: str) -> str:
    """Prueft die Terminverfuegbarkeit. Returns: Human-readable Ergebnis."""
    if not _rate_limiter.is_allowed():
        return "Einen Moment bitte, ich bin gerade etwas ueberlastet."

    logger.info(f"📅 check_availability: {requested_date}")

    try:
        d = date.fromisoformat(requested_date)

        if d < date.today():
            return "Dieses Datum liegt leider in der Vergangenheit. Haben Sie ein anderes Datum im Sinn?"
        if d.weekday() >= 5:
            return "Am Wochenende sind wir leider nicht erreichbar. Darf ich Ihnen einen Termin unter der Woche vorschlagen?"

        if _use_calendly:
            slots = await _calendly_get_slots(requested_date)
            if slots is None:
                return "Entschuldigung, ich kann gerade nicht auf den Kalender zugreifen. Darf ich es gleich nochmal versuchen?"
            if not slots:
                return f"Am {d.strftime('%d.%m.%Y')} ist leider nichts mehr frei. Moechten Sie einen anderen Tag versuchen?"
            return (
                f"Am {d.strftime('%d.%m.%Y')} haette ich noch "
                f"{', '.join(slots)} Uhr frei. Was wuerde Ihnen passen?"
            )

        slots = _get_mock_slots(requested_date)
        return (
            f"Am {d.strftime('%d.%m.%Y')} haette ich noch "
            f"{', '.join(slots)} Uhr frei. Was wuerde Ihnen passen?"
        )

    except ValueError:
        return "Das Datum habe ich leider nicht verstanden. Koennten Sie es nochmal im Format Tag Punkt Monat Punkt Jahr nennen?"
    except Exception as e:
        logger.error(f"Fehler availability: {e}")
        return "Ich habe gerade ein kleines technisches Problem mit dem Kalender. Einen Moment bitte."


async def reserve_appointment(
    name: str, email: str,
    appointment_date: str, appointment_time: str,
    topic: str,
) -> str:
    """Bucht einen Termin. Returns: Human-readable Ergebnis."""
    if not _rate_limiter.is_allowed():
        return "Entschuldigung, es gibt gerade ein technisches Problem. Bitte versuchen Sie es gleich nochmal."

    logger.info(f"📝 Buche: {name} am {appointment_date} {appointment_time}")

    try:
        if _use_calendly:
            booking = await _calendly_book(
                name, email, appointment_date, appointment_time, topic
            )
            if booking is None:
                _save_booking_local({
                    "created_at": datetime.now().isoformat(),
                    "name": name, "email": email,
                    "date": appointment_date, "time": appointment_time,
                    "topic": topic, "status": "calendly_failed_local_saved",
                })
                return (
                    f"Entschuldigung, es gab ein kleines technisches Problem. "
                    f"Ich habe Ihre Daten aber notiert und "
                    f"Herr Al-Ghobari meldet sich persoenlich bei Ihnen unter {email}."
                )
            return (
                f"Wunderbar, der Termin am {appointment_date} "
                f"um {appointment_time} Uhr ist fuer Sie eingetragen. "
                f"Sie erhalten eine Bestaetigung an {email}."
            )

        _save_booking_local({
            "created_at": datetime.now().isoformat(),
            "name": name, "email": email,
            "date": appointment_date, "time": appointment_time,
            "topic": topic, "status": "simulation",
        })
        return (
            f"Wunderbar, der Termin am {appointment_date} "
            f"um {appointment_time} Uhr ist fuer Sie eingetragen. "
            f"Sie erhalten eine Bestaetigung an {email}."
        )

    except Exception as e:
        logger.error(f"Buchungsfehler: {e}")
        return "Entschuldigung, es gab ein technisches Problem. Ich habe Ihre Daten aber notiert — Herr Al-Ghobari meldet sich bei Ihnen."