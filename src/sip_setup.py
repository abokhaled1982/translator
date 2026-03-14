"""
sip_setup.py — Registriert den Easybell SIP-Trunk bei LiveKit Cloud.

Einmalig ausführen:
  python src/sip_setup.py

Was passiert:
  1. SIP Inbound Trunk wird erstellt (Easybell → LiveKit)
  2. SIP Dispatch Rule wird erstellt (Anruf → Agent)

Danach: Easybell-Rufweiterleitung auf die LiveKit SIP-URI konfigurieren.
"""
import asyncio
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from livekit import api


async def setup():
    """Erstellt SIP Trunk + Dispatch Rule bei LiveKit Cloud."""

    lk_url = os.getenv("LIVEKIT_URL", "")
    lk_key = os.getenv("LIVEKIT_API_KEY", "")
    lk_secret = os.getenv("LIVEKIT_API_SECRET", "")

    sip_user = os.getenv("SIP_USERNAME", "")
    sip_pass = os.getenv("SIP_PASSWORD", "")
    sip_number = os.getenv("SIP_PHONE_NUMBER", "")

    if not all([lk_url, lk_key, lk_secret]):
        print("FEHLER: Fehlende LiveKit-Umgebungsvariablen. Prüfe .env!")
        sys.exit(1)

    # LiveKit API Client (HTTP, nicht WebSocket)
    http_url = lk_url.replace("wss://", "https://").replace("ws://", "http://")
    lk = api.LiveKitAPI(http_url, lk_key, lk_secret)

    try:
        # ── 1. Bestehende Trunks prüfen ──────────────────────────────
        print("Prüfe bestehende SIP Trunks...")
        existing = await lk.sip.list_sip_inbound_trunk(
            api.ListSIPInboundTrunkRequest()
        )

        trunk_id = None
        for trunk in existing.items:
            if "Easybell" in (trunk.name or ""):
                print(f"  Easybell-Trunk existiert bereits: {trunk.sip_trunk_id}")
                trunk_id = trunk.sip_trunk_id
                break

        if not trunk_id:
            # ── 2. Neuen SIP Inbound Trunk erstellen ─────────────────
            print("Erstelle SIP Inbound Trunk...")

            trunk_request = api.CreateSIPInboundTrunkRequest(
                trunk=api.SIPInboundTrunkInfo(
                    name="Easybell-Inbound",
                    numbers=[sip_number] if sip_number else [],
                    auth_username=sip_user,
                    auth_password=sip_pass,
                )
            )
            trunk_result = await lk.sip.create_sip_inbound_trunk(trunk_request)
            trunk_id = trunk_result.sip_trunk_id
            print(f"  Trunk erstellt: {trunk_id}")

        # ── 3. Bestehende Dispatch Rules prüfen ──────────────────────
        print("Prüfe bestehende Dispatch Rules...")
        rules = await lk.sip.list_sip_dispatch_rule(
            api.ListSIPDispatchRuleRequest()
        )

        rule_exists = False
        for rule in rules.items:
            if trunk_id in list(rule.trunk_ids or []):
                print(f"  Dispatch Rule existiert bereits: {rule.sip_dispatch_rule_id}")
                rule_exists = True
                break

        if not rule_exists:
            # ── 4. Dispatch Rule erstellen ────────────────────────────
            print("Erstelle Dispatch Rule (Anruf → Agent)...")

            rule_request = api.CreateSIPDispatchRuleRequest(
                name="Easybell-to-Agent",
                trunk_ids=[trunk_id],
                rule=api.SIPDispatchRule(
                    dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                        room_prefix="call-",
                        pin="",
                    )
                ),
                hide_phone_number=False,
            )
            rule_result = await lk.sip.create_sip_dispatch_rule(rule_request)
            print(f"  Dispatch Rule erstellt: {rule_result.sip_dispatch_rule_id}")

        # ── LiveKit SIP-URI berechnen ─────────────────────────────────
        # Format: sip:<trunk_id>@<livekit-host>
        lk_host = lk_url.replace("wss://", "").replace("ws://", "")
        sip_uri = f"sip:{trunk_id}@{lk_host}"

        print()
        print("=" * 60)
        print("SIP-Setup abgeschlossen!")
        print(f"  Trunk ID:      {trunk_id}")
        print(f"  Telefonnummer: {sip_number}")
        print("=" * 60)
        print()
        print("NÄCHSTER SCHRITT — Easybell konfigurieren:")
        print(f"  1. Geh ins Easybell-Portal → Rufnummern verwalten")
        print(f"  2. Rufweiterleitung aktivieren auf:")
        print(f"     {sip_uri}")
        print(f"  ODER: SIP-Registrar in Easybell auf LiveKit umstellen")
        print()
        print("Dann starte den Agent mit: python src/main.py prod")
        print("Und ruf deine Nummer an!")

    finally:
        await lk.aclose()


if __name__ == "__main__":
    asyncio.run(setup())
