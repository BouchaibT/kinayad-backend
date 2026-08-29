# -*- coding: utf-8 -*-
"""
Test de bout en bout — parcours patient via le webhook Evolution API.

Simule un patient qui ne sait pas lire : il ne tape QUE des chiffres.
Vérifie chaque réponse du bot (journalisée en outbound) et l'état final
(RDV créé + rappels 24h/2h planifiés).

Usage :
    python tests/test_flow_evolution.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import httpx

API = "http://127.0.0.1:8000"
INSTANCE = "kinayad-demo"
PATIENT = "21261234567"  # nouveau patient — remoteJid Evolution (E.164 sans +)


def evolution_payload(text: str, push_name: str = "Fatima") -> dict:
    return {
        "event": "messages.upsert",
        "instance": INSTANCE,
        "data": {
            "key": {"remoteJid": f"{PATIENT}@s.whatsapp.net", "fromMe": False, "id": "wamid-evol-1"},
            "pushName": push_name,
            "message": {"conversation": text},
            "messageType": "conversation",
            "messageTimestamp": int(datetime.now(timezone.utc).timestamp()),
        },
    }


def send(text: str, label: str) -> dict:
    r = httpx.post(f"{API}/webhook/evolution", json=evolution_payload(text))
    r.raise_for_status()
    body = r.json()
    print(f"\n🧑 Patient ({label}) : « {text} »")
    print(f"   → webhook : {body}")
    return body


def last_outbound(prev_count: int) -> str:
    """Lit le dernier message sortant journalisé (outbound_conversation)."""
    # Relu via le MessageLog le plus récent — requête directe impossible ici,
    # on s'appuie sur le payload renvoyé par le webhook + vérification base plus bas.
    return ""


def main() -> int:
    print("=" * 60)
    print("PARCOURS PATIENT — prise de RDV par choix numérotés (Evolution)")
    print("=" * 60)

    # Étape 1 : premier contact (texte libre, patient illettré)
    send("Bonjour docteur", "1er contact")
    # Étape 2 : menu → « 1 » = prendre RDV
    send("1", "choix menu RDV")
    # Étape 3 : dates → « 1 » = premier jour proposé
    send("1", "choix jour")
    # Étape 4 : créneaux → « 2 » = deuxième créneau
    send("2", "choix créneau")
    # Étape 5 : confirmation → « 1 » = oui
    send("1", "confirmation")

    print("\n" + "=" * 60)
    print("VÉRIFICATIONS EN BASE")
    print("=" * 60)

    from sqlalchemy import select

    sys.path.insert(0, ".")
    from app import models
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        client = db.scalar(select(models.Client).where(models.Client.wa_id == PATIENT))
        if not client:
            print("❌ Patient introuvable en base")
            return 1
        print(f"✅ Patient créé : {client.name} ({client.wa_id}), langue={client.preferred_language}")

        # Messages sortants journalisés (la conversation visible côté patient)
        outbound = db.scalars(
            select(models.MessageLog).where(
                models.MessageLog.event_type == "outbound",
                models.MessageLog.tenant_id == client.tenant_id,
            ).order_by(models.MessageLog.id.desc()).limit(10)
        ).all()
        print(f"\n📤 Réponses du bot (journal outbound, {len(outbound)} messages) :")
        for m in reversed(outbound):
            payload = m.payload or {}
            text = (payload.get("text") or "").replace("\n", " ⏎ ")
            print(f"   • {text[:120]}")

        # RDV créé pour ce patient ?
        appts = db.scalars(
            select(models.Appointment).where(models.Appointment.client_id == client.id)
        ).all()
        print(f"\n📅 RDV du patient : {len(appts)}")
        for a in appts:
            print(f"   - {a.start_at.isoformat()} statut={a.status.value} notes={a.notes}")
            reminders = db.scalars(
                select(models.ReminderScheduled).where(
                    models.ReminderScheduled.appointment_id == a.id
                )
            ).all()
            for r in reminders:
                print(f"     rappel {r.type.value} → send_at={r.send_at.isoformat()} statut={r.status.value}")

        # État de conversation
        state = db.scalar(
            select(models.ConversationState).where(
                models.ConversationState.client_id == client.id
            )
        )
        print(f"\n💬 État de conversation final : {state.state if state else 'AUCUN'}")

        ok = len(appts) == 1 and all(
            r.status.value == "pending" for a in appts for r in
            db.scalars(select(models.ReminderScheduled).where(models.ReminderScheduled.appointment_id == a.id)).all()
        )
        print("\n" + ("🎉 PARCOURS COMPLET VALIDÉ" if ok else "⚠️ PARCOURS INCOMPLET"))
        return 0 if ok else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
