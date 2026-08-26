# -*- coding: utf-8 -*-
"""
Route interne — déclenche un cycle d'envoi des rappels dus (WhatsApp).

Remplace le worker permanent (payant sur Render en plan gratuit) par un
déclenchement ponctuel, appelé périodiquement par un cron externe gratuit
(GitHub Actions). Protégée par la même clé API que les autres routes internes.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.bookings import require_api_key
from app.db.session import get_db
from app.services.reminders import send_due_reminders

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/run-reminders", dependencies=[Depends(require_api_key)])
def run_reminders(db: Session = Depends(get_db)):
    """Envoie tous les rappels WhatsApp actuellement dus (appelé par un cron externe)."""
    sent = send_due_reminders(db)
    if sent:
        logger.info("%s rappel(s) traité(s) via /internal/run-reminders", sent)
    return {"reminders_sent": sent}
