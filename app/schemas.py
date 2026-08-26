# -*- coding: utf-8 -*-
"""Schémas Pydantic (validations de la couche API et du worker)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# appointments
# ---------------------------------------------------------------------------


class AppointmentCreate(BaseModel):
    tenant_id: uuid.UUID
    practitioner_id: uuid.UUID | None = None
    wa_id: str = Field(..., description="Numéro WhatsApp du patient au format E.164")
    client_name: str | None = None
    phone_e164: str | None = None
    preferred_language: str = "fr"
    start_at: datetime
    duration_min: int = Field(30, ge=5, le=240)
    notes: str | None = None


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    practitioner_id: uuid.UUID | None
    client_id: uuid.UUID
    start_at: datetime
    duration_min: int
    status: str
    confirmation_sent_at: datetime | None
    reminder_24h_sent_at: datetime | None
    reminder_2h_sent_at: datetime | None
    cancelled_at: datetime | None


class AppointmentCancel(BaseModel):
    reason: str | None = None
