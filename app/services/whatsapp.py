# -*- coding: utf-8 -*-
"""
Service WhatsApp — envoi de messages via Evolution API (pont WhatsApp Web /
Baileys auto-hébergé), pas l'API officielle payante de Meta.

Chaque tenant est relié à UNE instance Evolution API (un numéro WhatsApp
connecté par scan de QR code), identifiée par `tenant.settings["evolution_instance"]`.
`demo_mode` (config) court-circuite l'appel HTTP réel (aucun message réel envoyé).
"""
from __future__ import annotations

import logging

import httpx

from app import models
from app.config import settings

logger = logging.getLogger(__name__)


def _send_evolution_text(instance: str, wa_id: str, text: str) -> str:
    """Envoie un message texte libre via Evolution API. Retourne l'id du message."""
    if not settings.evolution_api_url or not settings.evolution_api_key:
        raise RuntimeError(
            "EVOLUTION_API_URL / EVOLUTION_API_KEY non configurés : impossible d'envoyer un message réel."
        )
    url = f"{settings.evolution_api_url.rstrip('/')}/message/sendText/{instance}"
    headers = {"apikey": settings.evolution_api_key, "Content-Type": "application/json"}
    payload = {"number": wa_id, "text": text}
    resp = httpx.post(url, json=payload, headers=headers, timeout=20.0)
    if resp.status_code >= 400:
        logger.error("Evolution API send error %s: %s", resp.status_code, resp.text)
        raise RuntimeError(f"Evolution API error {resp.status_code}: {resp.text}")
    data = resp.json()
    return (data.get("key") or {}).get("id") or str(data.get("id") or "sent")


def send_text_reminder(tenant: models.Tenant, wa_id: str, text: str) -> str:
    """Envoie un rappel/texte libre via l'instance Evolution API du tenant (ou simule en démo)."""
    if settings.demo_mode:
        logger.info("[DEMO] envoi WhatsApp -> %s : %s", wa_id, text)
        return f"DEMO-{wa_id}"

    instance = (tenant.settings or {}).get("evolution_instance")
    if not instance:
        raise ValueError(
            f"Aucune instance Evolution API configurée pour le tenant '{tenant.slug}' "
            "(tenant.settings['evolution_instance'] manquant)."
        )
    return _send_evolution_text(instance, wa_id, text)
