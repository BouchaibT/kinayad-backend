# -*- coding: utf-8 -*-
"""
Routes du tableau de bord public (site vitrine Kinayad).

Lecture : KPI, RDV à venir, rappels, conversations en cours.
Écriture (protégée par le mot de passe dashboard, jamais la clé API interne) :
création d'un RDV depuis l'interface praticien et annulation.

La clé API interne protège les routes sensibles (déclenchement des rappels,
admin) et ne doit jamais être exposée côté navigateur. Les numéros WhatsApp
sont partiellement masqués dans les listes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import models
from app.config import settings
from app.db.session import SessionLocal, get_db
from app.services.reminders import create_appointment_and_schedule, normalize_wa_id


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
    appointment_id: uuid.UUID
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


class ConversationItem(BaseModel):
    client_name: str
    wa_id_masked: str
    state: str
    context_summary: str
    updated_at: datetime


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
                appointment_id=a.id,
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


@router.get("/{slug}/conversations", response_model=list[ConversationItem])
def active_conversations(slug: str, limit: int = Query(10, ge=1, le=50)):
    """Conversations WhatsApp en cours (état différent de IDLE)."""
    db = SessionLocal()
    try:
        tenant = _get_tenant_or_404(db, slug)
        rows = db.scalars(
            select(models.ConversationState)
            .options(joinedload(models.ConversationState.client))
            .where(
                models.ConversationState.tenant_id == tenant.id,
                models.ConversationState.state != "IDLE",
            )
            .order_by(models.ConversationState.updated_at.desc())
            .limit(limit)
        ).unique()

        context_labels = {
            "CHOOSING_DATE": "choisit un jour",
            "CHOOSING_SLOT": "choisit un créneau",
            "CONFIRMING": "confirme son RDV",
            "CANCELLING": "annule un RDV",
        }
        return [
            ConversationItem(
                client_name=c.client.name or _mask(None, c.client.wa_id),
                wa_id_masked=_mask(None, c.client.wa_id),
                state=c.state,
                context_summary=context_labels.get(c.state, c.state),
                updated_at=c.updated_at,
            )
            for c in rows
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


# ---------------------------------------------------------------------------
# Écriture — interface praticien (protégée par le mot de passe dashboard)
# ---------------------------------------------------------------------------


class DashboardBookingCreate(BaseModel):
    wa_id: str = Field(..., description="Numéro WhatsApp du patient (E.164, avec ou sans +)")
    client_name: str | None = None
    start_at: datetime = Field(..., description="Début du RDV (datetime ISO avec fuseau)")
    duration_min: int = Field(30, ge=5, le=240)
    practitioner_id: uuid.UUID | None = None


@router.post("/{slug}/bookings")
def dashboard_create_booking(slug: str, payload: DashboardBookingCreate, db: Session = Depends(get_db)):
    """Crée un RDV depuis le tableau de bord (praticien). Rappels 24h/2h planifiés."""
    tenant = _get_tenant_or_404(db, slug)

    practitioner_id = payload.practitioner_id
    if practitioner_id is not None:
        practitioner = db.get(models.Practitioner, practitioner_id)
        if not practitioner or practitioner.tenant_id != tenant.id:
            raise HTTPException(status_code=404, detail="Praticien introuvable pour ce cabinet")
    else:
        practitioner = db.scalar(
            select(models.Practitioner).where(
                models.Practitioner.tenant_id == tenant.id,
                models.Practitioner.is_active.is_(True),
            ).order_by(models.Practitioner.created_at.asc()).limit(1)
        )
        practitioner_id = practitioner.id if practitioner else None

    appointment, reminders = create_appointment_and_schedule(
        db,
        tenant_id=tenant.id,
        practitioner_id=practitioner_id,
        wa_id=normalize_wa_id(payload.wa_id),
        client_name=payload.client_name,
        phone_e164=f"+{normalize_wa_id(payload.wa_id)}",
        preferred_language="fr",
        start_at=payload.start_at,
        duration_min=payload.duration_min,
        notes="Créé depuis le tableau de bord.",
    )
    return {
        "appointment_id": str(appointment.id),
        "reminders_scheduled": len(reminders),
        "start_at": appointment.start_at.isoformat(),
    }


@router.delete("/{slug}/appointments/{appointment_id}")
def dashboard_cancel_appointment(slug: str, appointment_id: uuid.UUID, db: Session = Depends(get_db)):
    """Annule un RDV depuis le tableau de bord (même mécanisme que l'annulation patient)."""
    tenant = _get_tenant_or_404(db, slug)
    appointment = db.get(models.Appointment, appointment_id)
    if not appointment or appointment.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="RDV introuvable pour ce cabinet")
    if appointment.status == models.AppointmentStatus.CANCELLED:
        return {"id": str(appointment.id), "status": "cancelled", "already": True}
    appointment.status = models.AppointmentStatus.CANCELLED
    appointment.cancelled_at = datetime.now(timezone.utc)
    appointment.cancel_reason = "practitioner_dashboard"
    for r in appointment.reminders:
        if r.status in (models.ReminderStatus.PENDING, models.ReminderStatus.RETRYING):
            r.status = models.ReminderStatus.CANCELLED
    db.commit()
    return {"id": str(appointment.id), "status": "cancelled", "already": False}
