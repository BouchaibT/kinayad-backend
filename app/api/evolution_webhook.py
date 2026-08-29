# -*- coding: utf-8 -*-
"""
Webhook Evolution API — messages entrants WhatsApp (instance WhatsApp Web).

Format Evolution API v2 (event `messages.upsert`) :
    {
      "event": "messages.upsert",
      "instance": "<nom de l'instance>",
      "data": {
        "key": {"remoteJid": "212600000001@s.whatsapp.net", "fromMe": false, "id": "..."},
        "pushName": "Fatima",
        "message": {"conversation": "1"} | {"extendedTextMessage": {"text": "1"}},
        "messageType": "conversation",
        "messageTimestamp": 1750888919
      },
      "apikey": "..."
    }

Le tenant est retrouvé via `data.instance` (tenant.settings["evolution_instance"]).
Tout le traitement conversationnel vit dans app.services.conversation.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.db.session import SessionLocal
from app.services import conversation
from app.services.reminders import normalize_wa_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook/evolution", tags=["webhook-evolution"])


def _extract_text(msg: dict) -> str:
    """Extrait le texte d'un message WhatsApp (conversation ou extendedTextMessage)."""
    if not isinstance(msg, dict):
        return ""
    if isinstance(msg.get("conversation"), str):
        return msg["conversation"]
    etm = msg.get("extendedTextMessage") or {}
    if isinstance(etm.get("text"), str):
        return etm["text"]
    return ""


@router.post("")
async def receive_evolution(request: Request):
    """Réception des événements Evolution API (messages entrants principalement)."""
    db: Session = SessionLocal()
    try:
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

        # --- Sécurité minimale : l'apikey de l'instance, si fournie ---
        if settings.evolution_api_key:
            provided = (
                request.headers.get("apikey")
                or request.headers.get("x-evolution-apikey")
                or (payload.get("apikey") if isinstance(payload, dict) else None)
            )
            if provided and provided != settings.evolution_api_key:
                logger.warning("Webhook Evolution : apikey invalide rejetée")
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid apikey")

        event = payload.get("event") if isinstance(payload, dict) else None
        instance = payload.get("instance") if isinstance(payload, dict) else None
        data = payload.get("data") if isinstance(payload, dict) else {}

        # Seuls les messages entrants nous intéressent
        if event != "messages.upsert":
            return {"status": "ok", "ignored": event}
        key = data.get("key") or {}
        if key.get("fromMe"):
            return {"status": "ok", "ignored": "fromMe"}

        wa_id = normalize_wa_id(key.get("remoteJid", ""))
        text = _extract_text(data.get("message") or {})
        push_name = data.get("pushName")

        # Journalisation brute (audit) — même logique que le webhook Meta
        db.add(
            models.MessageLog(
                meta_object=f"evolution_instance_{instance}",
                event_type=event,
                payload={"wa_id": wa_id, "text": text, "push_name": push_name},
            )
        )
        db.commit()

        if not wa_id or not text:
            return {"status": "ok", "ignored": "empty"}

        # Tenant via l'instance Evolution
        tenant = None
        if instance:
            tenants = db.scalars(
                select(models.Tenant)
            ).all()
            for t in tenants:
                if (t.settings or {}).get("evolution_instance") == instance:
                    tenant = t
                    break
        if not tenant:
            logger.warning("Webhook Evolution : aucune instance '%s' rattachée à un tenant", instance)
            return {"status": "ok", "ignored": "no-tenant"}

        reply = conversation.handle_incoming_message(
            db, tenant=tenant, wa_id=wa_id, text=text, push_name=push_name
        )
        return {"status": "ok", "replied": bool(reply), "wa_id": wa_id}
    finally:
        db.close()
