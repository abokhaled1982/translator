"""Quick test for Calendly API integration."""
import httpx
import json

TOKEN = "eyJraWQiOiIxY2UxZTEzNjE3ZGNmNzY2YjNjZWJjY2Y4ZGM1YmFmYThhNjVlNjg0MDIzZjdjMzJiZTgzNDliMjM4MDEzNWI0IiwidHlwIjoiUEFUIiwiYWxnIjoiRVMyNTYifQ.eyJpc3MiOiJodHRwczovL2F1dGguY2FsZW5kbHkuY29tIiwiaWF0IjoxNzczMzk4NDQyLCJqdGkiOiJkMDkxOWExMS0wYTlkLTQ1ZmMtODdhZC0wZDQyYWQyM2FhMmMiLCJ1c2VyX3V1aWQiOiI2NTZkNmM1ZC00MjRkLTQ3NTYtOGE2ZS1mOTEwMGUxZThkMzciLCJzY29wZSI6ImF2YWlsYWJpbGl0eTpyZWFkIGF2YWlsYWJpbGl0eTp3cml0ZSBldmVudF90eXBlczpyZWFkIGV2ZW50X3R5cGVzOndyaXRlIGxvY2F0aW9uczpyZWFkIHJvdXRpbmdfZm9ybXM6cmVhZCBzaGFyZXM6d3JpdGUgc2NoZWR1bGVkX2V2ZW50czpyZWFkIHNjaGVkdWxlZF9ldmVudHM6d3JpdGUgc2NoZWR1bGluZ19saW5rczp3cml0ZSJ9.R-OYCarzj4NrtQySJi_SNqyUUDKxoj91nrBBCmwkWjmmlOu0Q8ZAoOmuLGEAWX62-cVwnANGva1NEO8ovE3ZNg"
EVENT_TYPE = "https://api.calendly.com/event_types/f8f14edc-710e-463c-9b75-d48acc6da3e2"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

print("=== Test 1: Verfügbarkeit prüfen (Mo 16.03.2026) ===")
r = httpx.get(
    "https://api.calendly.com/event_type_available_times",
    headers=HEADERS,
    params={
        "start_time": "2026-03-16T00:00:00.000000Z",
        "end_time": "2026-03-17T00:00:00.000000Z",
        "event_type": EVENT_TYPE,
    },
)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    slots = [s for s in data.get("collection", []) if s.get("status") == "available"]
    print(f"Freie Slots: {len(slots)}")
    for s in slots[:5]:
        print(f"  {s['start_time']}")
    if len(slots) > 5:
        print(f"  ... und {len(slots) - 5} weitere")
else:
    print(r.text)

print("\n=== Test 2: Scheduling Link erstellen ===")
r2 = httpx.post(
    "https://api.calendly.com/scheduling_links",
    headers=HEADERS,
    json={
        "max_event_count": 1,
        "owner": EVENT_TYPE,
        "owner_type": "EventType",
    },
)
print(f"Status: {r2.status_code}")
if r2.status_code in (200, 201):
    link = r2.json().get("resource", {}).get("booking_url", "")
    print(f"Booking URL: {link}")
else:
    print(r2.text)
