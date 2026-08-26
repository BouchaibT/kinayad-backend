# -*- coding: utf-8 -*-
"""
Routes du webhook Meta.

- GET  : vérification (verification token) exigée par Meta à l'installation.
- POST : réception des événements (messages + statuts). Vérité de la signature.
"""
from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import SessionLocal
from app.services.meta_webhook import handle_webhook

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])


def _verify_signature(request: Request, secret: str) -> bool:
    """Vérifie l'en-tête X-Hub-Signature-256 (HMAC-SHA256) envoyé par Meta."""
    signature = request.headers.get("X-Hub-Signature-256", "")
    try:
        # Meta envoie "sha256=<hex>"
        provided = signature.split("=", 1)[1]
    except IndexError:
        return False
    expected = hmac.new(secret.encode(), request.state.raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


@router.get("")
def verify(request: Request, hub_mode: str = "", hub_challenge: str = "", hub_verify_token: str = ""):
    """GET de validation demandé par Meta lors de la configuration du webhook."""
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification token mismatch")


@router.post("")
async def receive(request: Request):
    """Réception (POST) des événements Meta."""
    raw = await request.body()
    request.state.raw_body = raw  # stocké pour la vérification de signature

    db: Session = SessionLocal()
    try:
        # En démo on peut ignorer la signature ; en prod il faut le secret du webhook
        if not settings.demo_mode:
            webhook_secret = settings.meta_webhook_secret
            if not webhook_secret or not _verify_signature(request, webhook_secret):
                raise HTTPException(status_code=401, detail="Invalid signature")

        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        summary = handle_webhook(db, payload)
        logger.info("Webhook Meta traité : %s", summary)
        # Meta attend un 200 immédiat ; tout le traitement est synchrone ici (phase 1)
        return {"status": "ok", "summary": summary}
    finally:
        db.close()
