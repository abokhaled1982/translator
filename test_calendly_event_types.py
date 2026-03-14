import httpx
import os

token = os.getenv("CALENDLY_API_KEY")
url = "https://api.calendly.com/event_types?user=https://api.calendly.com/users/me"
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

r = httpx.get(url, headers=headers)
print(f"Status: {r.status_code}")
print(r.text)
