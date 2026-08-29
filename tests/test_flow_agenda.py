# -*- coding: utf-8 -*-
"""
Test 4 — agenda praticien : disponibilités, blocages, déplacement de RDV.

Vérifie :
1. Le bot propose les créneaux des heures d'ouverture MODIFIÉES
2. Les créneaux dans un blocage (vacances) sont exclus
3. Le déplacement d'un RDV re-planifie les rappels (statut → reporté)
4. La validation rejette des heures invalides

Usage : python tests/test_flow_agenda.py  (API locale sur 127.0.0.1:8000)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import httpx

API = "http://127.0.0.1:8000"
SLUG = "demo-cabinet-rabat"
KEY = "kinayad-demo-2026"
INSTANCE = "kinayad-demo"
PATIENT = "21261234001"
H = {"X-Dashboard-Key": KEY}
HJ = {**H, "Content-Type": "application/json"}


def evo(text: str) -> dict:
    return {
        "event": "messages.upsert",
        "instance": INSTANCE,
        "data": {
            "key": {"remoteJid": f"{PATIENT}@s.whatsapp.net", "fromMe": False, "id": "wa-1"},
            "pushName": "Agenda Test",
            "message": {"conversation": text},
            "messageType": "conversation",
            "messageTimestamp": int(datetime.now(timezone.utc).timestamp()),
        },
    }


def send(text: str):
    r = httpx.post(f"{API}/webhook/evolution", json=evo(text))
    r.raise_for_status()
    return r.json()


def outbound_logs() -> list[dict]:
    from sqlalchemy import select
    sys.path.insert(0, ".")
    from app import models
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        logs = db.scalars(select(models.MessageLog).where(
            models.MessageLog.event_type == "outbound",
        ).order_by(models.MessageLog.id.desc()).limit(20)).all()
        return [(m.payload or {}).get("text", "") for m in logs]
    finally:
        db.close()


def main() -> int:
    print("=" * 60)
    print("TEST 4 — AGENDA PRATICIEN")
    print("=" * 60)

    # --- 1. Heures d'ouverture modifiées : lundi 08h-13h ---
    hours = {"mon": [["08:00", "13:00"]],
             "tue": [["09:00", "12:00"], ["14:00", "17:00"]],
             "wed": [["09:00", "12:00"], ["14:00", "17:00"]],
             "thu": [["09:00", "12:00"], ["14:00", "17:00"]],
             "fri": [["09:00", "12:00"], ["14:00", "17:00"]]}
    r = httpx.put(f"{API}/public/dashboard/{SLUG}/availability/opening-hours", headers=HJ, json={"opening_hours": hours})
    r.raise_for_status()
    print("✅ 1. Heures d'ouverture mises à jour (lundi 08h-13h)")

    # --- 2. Blocage lundi 08h-10h (vacances matin) ---
    r = httpx.post(f"{API}/public/dashboard/{SLUG}/availability/blocked", headers=HJ,
                   json={"start_at": "2026-08-31T08:00:00+01:00", "end_at": "2026-08-31T10:00:00+01:00",
                         "reason": "Vacances matin"})
    r.raise_for_status()
    block_id = r.json()["id"]
    print("✅ 2. Blocage créé (lundi 08h-10h)")

    # --- 3. Validation : heure invalide rejetée ---
    r = httpx.put(f"{API}/public/dashboard/{SLUG}/availability/opening-hours", headers=HJ,
                  json={"opening_hours": {"mon": [["14:00", "09:00"]]}})
    print(f"✅ 3. Validation (créneau inversé) → HTTP {r.status_code} (400 attendu)")
    assert r.status_code == 400

    # --- 4. Le patient réserve le lundi : les créneaux 08h-10h ne doivent PAS apparaître ---
    send("Bonjour")
    send("1")          # prendre RDV
    send("1")          # lundi 31/08
    logs = outbound_logs()
    slots_msg = next((t for t in logs if "créneaux disponibles" in t or "crénaux" in t), "")
    print("   créneaux proposés lundi :", [l.strip() for l in slots_msg.splitlines() if "️⃣" in l])
    assert "08:00" not in slots_msg and "09:30" not in slots_msg, "Le bloc 08h-10h ne doit pas être proposé !"
    assert "10:00" in slots_msg and "12:30" in slots_msg, "Les créneaux après le bloc doivent être proposés"
    print("✅ 4. Le bot exclut les créneaux bloqués (10:00 proposé, 09:30 absent)")

    # --- 5. Terminer le RDV (10:00 = option 1) puis le déplacer ---
    send("1")          # créneau 10:00
    send("1")          # confirmer
    from sqlalchemy import select
    sys.path.insert(0, ".")
    from app import models
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        client = db.scalar(select(models.Client).where(models.Client.wa_id == PATIENT))
        appt = db.scalar(select(models.Appointment).where(
            models.Appointment.client_id == client.id,
            models.Appointment.status != models.AppointmentStatus.CANCELLED,
        ))
        old_start = appt.start_at
        n_reminders = len(appt.reminders)
        print(f"✅ 5. RDV créé le {old_start.isoformat()} ({n_reminders} rappels)")
    finally:
        db.close()

    # --- 6. Déplacer le RDV à mercredi 11:30 ---
    new_start = "2026-09-02T11:30:00+01:00"
    r = httpx.patch(f"{API}/public/dashboard/{SLUG}/appointments/{appt.id}", headers=HJ,
                    json={"start_at": new_start})
    r.raise_for_status()
    data = r.json()
    print("   reschedule :", data)
    assert data["status"] == "rescheduled"
    assert data["reminders_rescheduled"] == 2

    db = SessionLocal()
    try:
        fresh = db.get(models.Appointment, appt.id)
        from app.services.reminders import to_tenant_local
        new_local = to_tenant_local(fresh.start_at, fresh.tenant)
        assert new_local.strftime("%H:%M") == "11:30", f"Heure locale {new_local}"
        pending = [x for x in fresh.reminders if x.status.value == "pending"]
        r24 = next((x for x in fresh.reminders if x.type.value == "24h"), None)
        r2h = next((x for x in fresh.reminders if x.type.value == "2h"), None)
        r24_local = to_tenant_local(r24.send_at, fresh.tenant).strftime("%H:%M") if r24 else "?"
        r2h_local = to_tenant_local(r2h.send_at, fresh.tenant).strftime("%H:%M") if r2h else "?"
        print(f"✅ 6. RDV déplacé : {new_local.isoformat()} — {len(pending)} rappels pending (24h→{r24_local}, 2h→{r2h_local})")
        assert len(pending) == 2 and r24_local == "11:30" and r2h_local == "09:30"
    finally:
        db.close()

    # --- 7. Supprimer le blocage (le praticien revient disponible) ---
    r = httpx.delete(f"{API}/public/dashboard/{SLUG}/availability/blocked/{block_id}", headers=H)
    r.raise_for_status()
    print(f"✅ 7. Blocage supprimé ({r.json()})")

    print("\n🎉 TEST 4 — AGENDA PRATICIEN VALIDÉ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
