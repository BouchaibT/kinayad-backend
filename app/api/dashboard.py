# -*- coding: utf-8 -*-
"""
Routes de lecture pour le tableau de bord public (site vitrine Kinayad).

Volontairement en lecture seule (aucune écriture possible) et sans clé API :
la clé API protège les routes sensibles (création de RDV, déclenchement des
rappels) et ne doit jamais être exposée côté navigateur. Les numéros WhatsApp
sont partiellement masqués pour limiter l'exposition de données patients tant
qu'aucune authentification n'a été ajoutée sur cette page (voir README).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import models
from app.config import settings
from app.db.session import SessionLocal


def require_dashboard_key(x_dashboard_key: str = Header(default="")) -> None:
    if not settings.dashboard_password or x_dashboard_key != settings.dashboard_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Mot de passe invalide")


router = APIRouter(
    prefix="/public/dashboard", tags=["dashboard"], dependencies=[Depends(require_dashboard_key)]
)


def _mask(name: str | None, wa_id: str) -> str:
    if name:
        return name
    return "•" * max(len(wa_id) - 2, 0) + wa_id[-2:]


def _get_tenant_or_404(db: Session, slug: str) -> models.Tenant:
    tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == slug))
    if not tenant:
        raise HTTPException(status_code=404, detail="Cabinet introuvable")
    return tenant


class SummaryOut(BaseModel):
    tenant_name: str
    appointments_today: int
    confirmation_rate_pct: float | None
    no_show_rate_pct: float | None
    reminders_sent_7d: int
    reminders_pending: int


class AppointmentItem(BaseModel):
    client_name: str
    start_at: datetime
    duration_min: int
    status: str
    practitioner_name: str | None


class ReminderItem(BaseModel):
    client_name: str
    type: str
    send_at: datetime
    status: str


@router.get("/{slug}/summary", response_model=SummaryOut)
def dashboard_summary(slug: str):
    db = SessionLocal()
    try:
        tenant = _get_tenant_or_404(db, slug)
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        appointments_today = db.scalar(
            select(func.count(models.Appointment.id)).where(
                models.Appointment.tenant_id == tenant.id,
                models.Appointment.start_at >= today_start,
                models.Appointment.start_at < today_end,
                models.Appointment.status != models.AppointmentStatus.CANCELLED,
            )
        ) or 0

        confirmed_or_done = db.scalar(
            select(func.count(models.Appointment.id)).where(
                models.Appointment.tenant_id == tenant.id,
                models.Appointment.status.in_(
                    [models.AppointmentStatus.CONFIRMED, models.AppointmentStatus.COMPLETED]
                ),
            )
        ) or 0
        non_cancelled = db.scalar(
            select(func.count(models.Appointment.id)).where(
                models.Appointment.tenant_id == tenant.id,
                models.Appointment.status != models.AppointmentStatus.CANCELLED,
            )
        ) or 0
        confirmation_rate = (
            round(100 * confirmed_or_done / non_cancelled, 1) if non_cancelled else None
        )

        no_shows = db.scalar(
            select(func.count(models.Appointment.id)).where(
                models.Appointment.tenant_id == tenant.id,
                models.Appointment.status == models.AppointmentStatus.NO_SHOW,
            )
        ) or 0
        resolved = db.scalar(
            select(func.count(models.Appointment.id)).where(
                models.Appointment.tenant_id == tenant.id,
                models.Appointment.status.in_(
                    [models.AppointmentStatus.COMPLETED, models.AppointmentStatus.NO_SHOW]
                ),
            )
        ) or 0
        no_show_rate = round(100 * no_shows / resolved, 1) if resolved else None

        reminders_sent_7d = db.scalar(
            select(func.count(models.ReminderScheduled.id)).where(
                models.ReminderScheduled.tenant_id == tenant.id,
                models.ReminderScheduled.status == models.ReminderStatus.SENT,
                models.ReminderScheduled.processed_at >= now - timedelta(days=7),
            )
        ) or 0

        reminders_pending = db.scalar(
            select(func.count(models.ReminderScheduled.id)).where(
                models.ReminderScheduled.tenant_id == tenant.id,
                models.ReminderScheduled.status.in_(
                    [models.ReminderStatus.PENDING, models.ReminderStatus.RETRYING]
                ),
            )
        ) or 0

        return SummaryOut(
            tenant_name=tenant.name,
            appointments_today=appointments_today,
            confirmation_rate_pct=confirmation_rate,
            no_show_rate_pct=no_show_rate,
            reminders_sent_7d=reminders_sent_7d,
            reminders_pending=reminders_pending,
        )
    finally:
        db.close()


@router.get("/{slug}/appointments/upcoming", response_model=list[AppointmentItem])
def upcoming_appointments(slug: str, limit: int = Query(10, ge=1, le=50)):
    db = SessionLocal()
    try:
        tenant = _get_tenant_or_404(db, slug)
        now = datetime.now(timezone.utc)
        rows = db.scalars(
            select(models.Appointment)
            .options(
                joinedload(models.Appointment.client),
                joinedload(models.Appointment.practitioner),
            )
            .where(
                models.Appointment.tenant_id == tenant.id,
                models.Appointment.start_at >= now,
                models.Appointment.status != models.AppointmentStatus.CANCELLED,
            )
            .order_by(models.Appointment.start_at.asc())
            .limit(limit)
        ).unique()

        return [
            AppointmentItem(
                client_name=_mask(a.client.name, a.client.wa_id),
                start_at=a.start_at,
                duration_min=a.duration_min,
                status=a.status.value,
                practitioner_name=a.practitioner.name if a.practitioner else None,
            )
            for a in rows
        ]
    finally:
        db.close()


@router.get("/{slug}/reminders/upcoming", response_model=list[ReminderItem])
def upcoming_reminders(slug: str, limit: int = Query(10, ge=1, le=50)):
    db = SessionLocal()
    try:
        tenant = _get_tenant_or_404(db, slug)
        rows = db.scalars(
            select(models.ReminderScheduled)
            .options(joinedload(models.ReminderScheduled.client))
            .where(
                models.ReminderScheduled.tenant_id == tenant.id,
                models.ReminderScheduled.status.in_(
                    [models.ReminderStatus.PENDING, models.ReminderStatus.RETRYING]
                ),
            )
            .order_by(models.ReminderScheduled.send_at.asc())
            .limit(limit)
        ).unique()

        return [
            ReminderItem(
                client_name=_mask(r.client.name, r.client.wa_id),
                type=r.type.value,
                send_at=r.send_at,
                status=r.status.value,
            )
            for r in rows
        ]
    finally:
        db.close()
