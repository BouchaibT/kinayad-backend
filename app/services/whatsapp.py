# -*- coding: utf-8 -*-
"""
Service WhatsApp — envoi de messages via l'API Cloud de Meta.

Règles clés :
- On envoie UNIQUEMENT depuis un WABA/Phone/Token PROPRE au tenant (déchiffré à la volée).
- En production on vérifie la fenêtre de 24h / usage de template approuvé.
- `demo_mode` (config) short-circuite l'appel HTTP réel (phase 1 : coût nul).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging

import httpx
from cryptography.fernet import Fernet

from app import models
from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Chiffrement / déchiffrement du token Meta
# ---------------------------------------------------------------------------


def _safe_fernet() -> Fernet:
    """Construit un Fernet (AES-128-CBC + HMAC) à partir de la clé en config.

    Si la clé est absente, on lève une erreur claire (ne JAMAIS envoyer un
    token en clair simplement parce que la clé manque).
    """
    if not settings.encryption_key_b64:
        raise RuntimeError(
            "ENCRYPTION_KEY_B64 non défini. Le token WhatsApp ne peut pas être déchiffré. "
            "Générez-le avec : python -c \"import os,base64;print(base64.b64encode(os.urandom(32)).decode())\""
        )
    try:
        key = base64.urlsafe_b64decode(settings.encryption_key_b64.encode())
    except binascii.Error:
        raise RuntimeError("Clef d'encryption invalide (doit être base64 url-safe).")
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_token(plain: str) -> str:
    return _safe_fernet().encrypt(plain.encode()).decode()


def decrypt_token(cipher: str | None) -> str:
    if not cipher:
        raise ValueError("Token WhatsApp manquant pour ce tenant.")
    return _safe_fernet().decrypt(cipher.encode()).decode()


# ---------------------------------------------------------------------------
# Appel API Meta Cloud
# ---------------------------------------------------------------------------


def _send_text_message(phone_number_id: int, access_token: str, wa_id: str, text: str) -> str:
    """Envoie un message texte et retourne le wamid (Message ID Meta).

    NOTE : le texte libre n'est permis QUE dans la fenêtre de 24h d'une
    conversation démarrée par le client. Pour les rappels sortants 24h/2h il
    FAUT un template approuvé (voir service reminders). Cette fonction reste
    utile pour une réponse dans la fenêtre.
    """
    url = f"{settings.meta_api_url}/{settings.meta_graph_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "text",
        "text": {"body": text},
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    resp = httpx.post(url, json=payload, headers=headers, timeout=15.0)
    if resp.status_code >= 400:
        logger.error("Meta send error %s: %s", resp.status_code, resp.text)
        raise RuntimeError(f"Meta API error {resp.status_code}: {resp.text}")
    data = resp.json()
    return data["messages"][0]["id"]


def _send_template_message(
    phone_number_id: int, access_token: str, wa_id: str, template_name: str, language: str, variables: list[str]
) -> str:
    """Envoie un message TEMPLATE (obligatoire en dehors de la fenêtre de 24h)."""
    url = f"{settings.meta_api_url}/{settings.meta_graph_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": v} for v in variables]}],
        },
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    resp = httpx.post(url, json=payload, headers=headers, timeout=15.0)
    if resp.status_code >= 400:
        logger.error("Meta template send error %s: %s", resp.status_code, resp.text)
        raise RuntimeError(f"Meta API error {resp.status_code}: {resp.text}")
    data = resp.json()
    return data["messages"][0]["id"]


def send_template_reminder(
    tenant: models.Tenant, wa_id: str, template_name: str, variables: list[str], language: str = "fr"
) -> str:
    """Envoie un template via les ressources du tenant (mode réel ou démo).

    `language` provient du client (`client.preferred_language`) et doit
    correspondre au code de langue du template Meta choisi (voir reminders._template_for).
    """
    if settings.demo_mode:
        logger.info("[DEMO] envoi template %s -> %s (lang=%s, vars=%s)", template_name, wa_id, language, variables)
        return f"DEMO-{template_name}-{wa_id}"

    token = decrypt_token(tenant.access_token_cipher)
    if not tenant.phone_number_id:
        raise ValueError("tenant.phone_number_id absent")
    return _send_template_message(
        tenant.phone_number_id, token, wa_id, template_name, language, variables
    )


# ---------------------------------------------------------------------------
# Vérification de la signature webhook
# ---------------------------------------------------------------------------


def verify_webhook_signature(payload_body: bytes, x_hub_signature_256: str | None) -> bool:
    """Vérifie l'en-tête `X-Hub-Signature-256` fourni par Meta.

    Le client inclut l'en-tête `X-Hub-Signature-256` calculé avec l'app secret
    de l'App Meta partagée de Kinayad.
    """
    if not x_hub_signature_256:
        return False
    if not settings.meta_app_secret:
        raise RuntimeError("META_APP_SECRET non configuré : impossible de valider les signatures.")
    signature_hex = hmac.new(
        settings.meta_app_secret.encode(), payload_body, hashlib.sha256
    ).hexdigest()
    expected = f"sha256={signature_hex}"
    return hmac.compare_digest(expected, x_hub_signature_256)
