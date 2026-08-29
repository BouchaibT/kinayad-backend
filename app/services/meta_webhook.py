# -*- coding: utf-8 -*-
"""
Service webhook — ingestion des événements Meta.

Objectif de Kinayad : le webhook est le point d'entrée qui capture
- les messages entrants des patients (confirmation, annulation, mentions "stop"),
- les statuts d'envoi (délivré / lu).
On journalise TOUT dans message_logs pour audit et debugging.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)


def handle_webhook(db: Session, payload: dict) -> dict:
    """Point d'entrée principal du webhook Meta.

    Retourne un résumé {entries, changes, messages} pour les logs.
    Structure Meta (v19.0) :
        {"entry": [ {"id": waba_id, "changes": [ {"field": "messages",
            "value": {"messaging_product": "whatsapp", "metadata": {...},
                       "contacts": [...], "messages": [...] }} ] } ] }
    """
    entries = payload.get("entry") or []
    summary = {"entries": len(entries), "changes": 0, "messages": []}

    for entry in entries:
        waba_id = entry.get("id")
        for change in entry.get("changes", []):
            summary["changes"] += 1
            field = change.get("field")
            value = change.get("value", {}) or {}

            # Journaliser le payload brut (audit)
            db.add(
                models.MessageLog(
                    meta_object=f"waba_{waba_id}",
                    event_type=field,
                    payload=value,
                )
            )

            if field == "messages":
                phones_value = value
                _handle_messages(db, value, summary)

    db.commit()
    return summary


def _handle_messages(db: Session, value: dict, summary: dict) -> None:
    messages = value.get("messages") or []
    contacts = value.get("contacts") or []
    metadata = value.get("metadata", {}) or {}
    phone_number_id = metadata.get("phone_number_id")

    # Associer le tenant via son phone_number_id (unique)
    tenant = None
    if phone_number_id:
        tenant = db.scalar(
            select(models.Tenant).where(models.Tenant.phone_number_id == phone_number_id)
        )

    for contact in contacts:
        wa_id = contact.get("wa_id")
        push_name = (contact.get("profile") or {}).get("name")
        for msg in messages:
            msg_id = msg.get("id")
            msg_type = msg.get("type")
            body = (msg.get("text") or {}).get("body", "") if msg_type == "text" else ""

            summary["messages"].append({"id": msg_id, "type": msg_type, "wa_id": wa_id, "text": body})
            if not tenant:
                logger.warning("Webhook pour phone_number_id %s sans tenant associé", phone_number_id)
                continue

            # Le gestionnaire de conversation (menus chiffrés) traite TOUT :
            # opt-out ("stop"/"0"), prise de RDV, annulation, horaires…
            try:
                from app.services import conversation

                reply = conversation.handle_incoming_message(
                    db, tenant=tenant, wa_id=wa_id, text=body, push_name=push_name
                )
                if reply:
                    summary["messages"][-1]["replied"] = True
            except Exception:  # noqa: BLE001 — le webhook ne doit jamais planter
                logger.exception("Erreur conversation pour %s", wa_id)


def _opt_out(db: Session, tenant: models.Tenant, wa_id: str) -> None:
    from datetime import datetime, timezone

    client = _find_client(db, tenant.id, wa_id)
    if client:
        client.opted_out_at = datetime.now(timezone.utc)
        client.opted_out_reason = "user_stop"
        logger.info("Opt-out enregistré pour %s (tenant %s)", wa_id, tenant.id)
    _append_audit(db, tenant, "client.opted_out", {"wa_id": wa_id})


def _reply_confirmed(db: Session, tenant: models.Tenant, wa_id: str) -> None:
    # Confirmation d'un RDV futur non encore confirmé (ex. premier RDV planifié.confirmé)
    _append_audit(db, tenant, "client.confirmed", {"wa_id": wa_id})
    logger.info("Confirmation reçue de %s (tenant %s)", wa_id, tenant.id)


def _reply_manage(db: Session, tenant: models.Tenant, wa_id: str) -> None:
    # Relais simple : on note l'intention d'annulation pour le praticien.
    _append_audit(db, tenant, "client.cancel_request", {"wa_id": wa_id})
    logger.info("Demande d'annulation de %s (tenant %s)", wa_id, tenant.id)


def _find_client(db: Session, tenant_id, wa_id) -> models.Client | None:
    from sqlalchemy import select

    return db.scalar(
        select(models.Client).where(models.Client.tenant_id == tenant_id, models.Client.wa_id == wa_id)
    )


def _append_audit(db: Session, tenant: models.Tenant, action: str, details: dict) -> None:
    db.add(
        models.AuditLog(
            tenant_id=tenant.id, actor_type="system", action=action, details=details
        )
    )
