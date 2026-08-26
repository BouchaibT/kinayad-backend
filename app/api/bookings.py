# -*- coding: utf-8 -*-
"""
Routes internes (protégées par clé API) — adaptées à la phase 1.

En phase 1 la "prise de RDV" se fait depuis un dashboard simple ou une
intégration web ; le schéma SQL + la base de données suffisent. Cette route
expose donc la création de RDV + planification des rappels en une transaction.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.db.session import get_db
from app.services.reminders import create_appointment_and_schedule

logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["bookings"])


# ---------------------------------------------------------------------------
# Auxiliaires / guards
# ---------------------------------------------------------------------------


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.api_keys or x_api_key not in settings.api_keys:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def get_tenant_or_404(db: Session, tenant_id: uuid.UUID) -> models.Tenant:
    tenant = db.get(models.Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant introuvable")
    return tenant


# ---------------------------------------------------------------------------
# Schémas
# ---------------------------------------------------------------------------


class BookingCreate(BaseModel):
    tenant_id: uuid.UUID
    practitioner_id: uuid.UUID | None = None
    wa_id: str = Field(..., description="Numéro WhatsApp du patient au format E.164")
    client_name: str | None = None
    phone_e164: str | None = None
    preferred_language: str = Field("fr", description="fr / ar / ar_MA")
    start_at: datetime = Field(..., description="Début du RDV (datetime ISO avec fuseau)")
    duration_min: int = Field(30, ge=5, le=240)
    notes: str | None = None


class BookingOut(BaseModel):
    appointment_id: uuid.UUID
    reminders_scheduled: int

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/bookings", response_model=BookingOut, dependencies=[Depends(require_api_key)])
def create_booking(payload: BookingCreate, db: Session = Depends(get_db)):
    """Crée un RDV confirmé + planifie les rappels 24h et 2h, atomiquement."""
    get_tenant_or_404(db, payload.tenant_id)

    if payload.practitioner_id is not None:
        practitioner = db.get(models.Practitioner, payload.practitioner_id)
        if not practitioner or practitioner.tenant_id != payload.tenant_id:
            raise HTTPException(status_code=404, detail="Praticien introuvable pour ce tenant")

    appointment, reminders = create_appointment_and_schedule(
        db,
        tenant_id=payload.tenant_id,
        practitioner_id=payload.practitioner_id,
        wa_id=payload.wa_id,
        client_name=payload.client_name,
        phone_e164=payload.phone_e164,
        preferred_language=payload.preferred_language,
        start_at=payload.start_at,
        duration_min=payload.duration_min,
        notes=payload.notes,
    )
    logger.info(
        "RDV %s créé (tenant %s, client %s), %d rappels planifiés",
        appointment.id, payload.tenant_id, payload.wa_id, len(reminders),
    )
    return BookingOut(appointment_id=appointment.id, reminders_scheduled=len(reminders))
