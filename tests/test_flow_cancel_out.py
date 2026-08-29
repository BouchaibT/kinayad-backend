# -*- coding: utf-8 -*-
"""
Test 2 — annulation de RDV, opt-out (stop), et webhook Meta.

Usage :
    python tests/test_flow_cancel_out.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import httpx

API = "http://127.0.0.1:8000"
INSTANCE = "kinayad-demo"
PATIENT = "21261234567"  # le patient créé par test_flow_evolution.py


def evo(text: str) -> dict:
    return {
        "event": "messages.upsert",
        "instance": INSTANCE,
        "data": {
            "key": {"remoteJid": f"{PATIENT}@s.whatsapp.net", "fromMe": False, "id": "wamid-evol-c1"},
            "pushName": "Fatima",
            "message": {"conversation": text},
            "messageType": "conversation",
            "messageTimestamp": int(datetime.now(timezone.utc).timestamp()),
        },
    }


def meta(text: str) -> dict:
    """Payload webhook Meta (format Cloud API v19)."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": 999999999},
                    "contacts": [{"wa_id": "21269999999", "profile": {"name": "Karim"}}],
                    "messages": [{"from": "21269999999", "id": "wamid-meta-1",
                                  "type": "text", "text": {"body": text}}],
                },
            }],
        }],
    }


def send_evo(text: str, label: str) -> None:
    r = httpx.post(f"{API}/webhook/evolution", json=evo(text))
    r.raise_for_status()
    print(f"🧑 {label} : « {text} » → {r.json()}")


def send_meta(text: str, label: str) -> None:
    r = httpx.post(f"{API}/webhook", json=meta(text))
    r.raise_for_status()
    print(f"🧑 {label} (Meta) : « {text} » → {r.json()}")


def main() -> int:
    print("=" * 60)
    print("TEST 2 — annulation, opt-out, webhook Meta")
    print("=" * 60)

    print("\n--- 1. ANNULATION (menu 2 → choix du RDV → 1) ---")
    send_evo("2", "menu → annuler")
    send_evo("1", "annuler le RDV affiché")

    print("\n--- 2. OPT-OUT (0) puis silence total ---")
    send_evo("0", "opt-out")
    r = httpx.post(f"{API}/webhook/evolution", json=evo("Bonjour ?"))
    print(f"🧑 Après opt-out, message ignoré → {r.json()}")
    assert r.json()["replied"] is False, "Le patient opt-out ne doit plus recevoir de réponse"

    print("\n--- 3. WEBHOOK META (même moteur de conversation) ---")
    send_meta("Salut docteur", "1er contact Meta")

    print("\n--- VÉRIFICATIONS EN BASE ---")
    from sqlalchemy import select

    sys.path.insert(0, ".")
    from app import models
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        client = db.scalar(select(models.Client).where(models.Client.wa_id == PATIENT))
        appts = db.scalars(select(models.Appointment).where(models.Appointment.client_id == client.id)).all()
        cancelled = [a for a in appts if a.status.value == "cancelled"]
        reminders_cancelled = db.scalars(
            select(models.ReminderScheduled).where(
                models.ReminderScheduled.appointment_id.in_([a.id for a in cancelled])
            )
        ).all()
        print(f"✅ RDV annulé : {len(cancelled)} (raison={cancelled[0].cancel_reason if cancelled else 'N/A'})")
        print(f"✅ Rappels liés annulés : {all(r.status.value == 'cancelled' for r in reminders_cancelled) if reminders_cancelled else 'aucun'}")
        db.refresh(client)
        print(f"✅ Opt-out enregistré : {client.opted_out_at is not None} (raison={client.opted_out_reason})")

        karim = db.scalar(select(models.Client).where(models.Client.wa_id == "21269999999"))
        print(f"✅ Patient Meta créé : {karim.name if karim else 'NON'} ({karim.wa_id if karim else '?'})")
        ok = len(cancelled) == 1 and client.opted_out_at is not None and karim is not None
        print("\n" + ("🎉 TEST 2 VALIDÉ" if ok else "⚠️ INCOMPLET"))
        return 0 if ok else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
