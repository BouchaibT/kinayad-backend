# -*- coding: utf-8 -*-
"""
Routes d'administration — création d'un cabinet (tenant) + praticien.

Protégées par la même clé API que les autres routes sensibles. Idempotentes :
rejouer la même requête ne duplique rien (upsert sur le slug / nom).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.api.bookings import require_api_key
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_api_key)])


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "cabinet"


class TenantCreate(BaseModel):
    name: str = Field(..., description="Nom du cabinet affiché aux patients")
    timezone: str = "Africa/Casablanca"
    plan: str = "pro"
    practitioner_name: str = Field(..., description="Nom du praticien")
    practitioner_profession: str | None = None
    practitioner_phone: str | None = Field(None, description="Numéro de contact, format E.164")


class TenantOut(BaseModel):
    tenant_id: uuid.UUID
    slug: str
    practitioner_id: uuid.UUID


@router.post("/tenants", response_model=TenantOut)
def create_tenant(payload: TenantCreate, db: Session = Depends(get_db)):
    slug = _slugify(payload.name)

    tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == slug))
    if not tenant:
        try:
            plan = models.TenantPlan(payload.plan)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Plan invalide : {payload.plan}")
        tenant = models.Tenant(
            slug=slug,
            name=payload.name,
            timezone=payload.timezone,
            plan=plan,
            status=models.TenantStatus.ACTIVE,
            settings={"demo": False},
        )
        db.add(tenant)
        db.flush()

    practitioner = db.scalar(
        select(models.Practitioner).where(
            models.Practitioner.tenant_id == tenant.id,
            models.Practitioner.name == payload.practitioner_name,
        )
    )
    if not practitioner:
        practitioner = models.Practitioner(
            tenant_id=tenant.id,
            name=payload.practitioner_name,
            profession=payload.practitioner_profession,
            cabinet_name=payload.name,
            phone=payload.practitioner_phone,
            is_active=True,
        )
        db.add(practitioner)
        db.flush()

    db.commit()
    return TenantOut(tenant_id=tenant.id, slug=tenant.slug, practitioner_id=practitioner.id)


class EvolutionLink(BaseModel):
    instance: str = Field(..., description="Nom de l'instance Evolution API (WhatsApp connecté)")
    number: str | None = Field(None, description="Numéro WhatsApp connecté à cette instance, pour référence")


@router.patch("/tenants/{slug}/evolution")
def link_evolution_instance(slug: str, payload: EvolutionLink, db: Session = Depends(get_db)):
    tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == slug))
    if not tenant:
        raise HTTPException(status_code=404, detail="Cabinet introuvable")
    updated = {**(tenant.settings or {}), "evolution_instance": payload.instance}
    if payload.number:
        updated["evolution_instance_number"] = payload.number
    tenant.settings = updated
    db.commit()
    return {"slug": tenant.slug, "evolution_instance": payload.instance, "evolution_instance_number": payload.number}


class TenantDetail(BaseModel):
    slug: str
    name: str
    timezone: str
    plan: str
    status: str
    settings: dict


@router.get("/tenants/{slug}", response_model=TenantDetail)
def get_tenant(slug: str, db: Session = Depends(get_db)):
    """Lecture seule — diagnostic (aucune route ne permettait de relire un tenant existant)."""
    tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == slug))
    if not tenant:
        raise HTTPException(status_code=404, detail="Cabinet introuvable")
    return TenantDetail(
        slug=tenant.slug,
        name=tenant.name,
        timezone=tenant.timezone,
        plan=tenant.plan.value,
        status=tenant.status.value,
        settings=tenant.settings or {},
    )


class TimezoneUpdate(BaseModel):
    timezone: str = Field(..., description="Fuseau IANA (ex. Africa/Casablanca)")


@router.patch("/tenants/{slug}/timezone")
def set_tenant_timezone(slug: str, payload: TimezoneUpdate, db: Session = Depends(get_db)):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == slug))
    if not tenant:
        raise HTTPException(status_code=404, detail="Cabinet introuvable")
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail=f"Fuseau IANA invalide : {payload.timezone}")
    tenant.timezone = payload.timezone
    db.commit()
    return {"slug": tenant.slug, "timezone": tenant.timezone}


class AppointmentAdminItem(BaseModel):
    id: uuid.UUID
    client_name: str | None
    wa_id: str
    start_at: str
    status: str


@router.get("/tenants/{slug}/appointments", response_model=list[AppointmentAdminItem])
def list_appointments(slug: str, db: Session = Depends(get_db)):
    """Lecture seule — diagnostic/nettoyage (aucune route n'exposait les RDV avec leur id)."""
    tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == slug))
    if not tenant:
        raise HTTPException(status_code=404, detail="Cabinet introuvable")
    rows = db.scalars(
        select(models.Appointment)
        .where(models.Appointment.tenant_id == tenant.id)
        .order_by(models.Appointment.start_at.asc())
    ).unique()
    return [
        AppointmentAdminItem(
            id=a.id,
            client_name=a.client.name if a.client else None,
            wa_id=a.client.wa_id if a.client else "",
            start_at=a.start_at.isoformat(),
            status=a.status.value,
        )
        for a in rows
    ]


@router.delete("/appointments/{appointment_id}")
def cancel_appointment(appointment_id: uuid.UUID, db: Session = Depends(get_db)):
    """Annule un RDV (même mécanisme que l'annulation patient : statut + rappels
    en attente annulés, rien n'est supprimé de la base pour garder la traçabilité)."""
    appointment = db.get(models.Appointment, appointment_id)
    if not appointment:
        raise HTTPException(status_code=404, detail="RDV introuvable")
    if appointment.status == models.AppointmentStatus.CANCELLED:
        return {"id": str(appointment.id), "status": "cancelled", "already": True}
    appointment.status = models.AppointmentStatus.CANCELLED
    appointment.cancelled_at = datetime.now(timezone.utc)
    appointment.cancel_reason = "admin_cleanup"
    for r in appointment.reminders:
        if r.status in (models.ReminderStatus.PENDING, models.ReminderStatus.RETRYING):
            r.status = models.ReminderStatus.CANCELLED
    db.commit()
    return {"id": str(appointment.id), "status": "cancelled", "already": False}
