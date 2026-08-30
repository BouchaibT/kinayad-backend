# -*- coding: utf-8 -*-
"""
Service de rappels — cœeur de Kinayad.

Deux responsabilités :
1. Planifier les rappels à la prise de RDV (transaction BEGIN/COMMIT).
2. Worker : parcourir `reminders_scheduled` et envoyer les rappels dus.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.services import cards, whatsapp

logger = logging.getLogger(__name__)

_WEEKDAYS_FR = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi", 4: "Vendredi", 5: "Samedi", 6: "Dimanche"}
_REMINDER_KIND = {
    models.ReminderType.REMINDER_24H: "Rappel 24h",
    models.ReminderType.REMINDER_2H: "Rappel 2h",
    models.ReminderType.CONFIRMATION: "Confirmation",
}


def tenant_zoneinfo(tenant: "models.Tenant | None") -> ZoneInfo:
    """Fuseau horaire du cabinet (Africa/Casablanca par défaut) — jamais celui du serveur.

    Toutes les heures RDV sont stockées en UTC (DateTime(timezone=True)) ; ce fuseau
    sert uniquement à l'affichage et à l'interprétation des horaires d'ouverture, qui
    sont exprimés en heure locale du cabinet, pas en UTC.
    """
    tz_name = (tenant.timezone if tenant else None) or "Africa/Casablanca"
    try:
        return ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — nom de fuseau invalide en base, ne jamais planter
        return ZoneInfo("Africa/Casablanca")


def to_tenant_local(dt: datetime, tenant: "models.Tenant | None") -> datetime:
    """Convertit un datetime (UTC ou naïf, considéré UTC) vers l'heure locale du cabinet."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tenant_zoneinfo(tenant))


def normalize_wa_id(wa_id: str | None) -> str:
    """Normalise un identifiant WhatsApp en E.164 sans « + » ni espaces.

    « +212600000003 » et « 212600000003 » (remoteJid Evolution) deviennent
    tous deux « 212600000003 » — un seul client par patient, quel que soit
    le canal d'entrée (webhook Meta / webhook Evolution / API bookings).
    """
    if not wa_id:
        return ""
    cleaned = wa_id.strip().lstrip("+").replace(" ", "").replace("-", "")
    # Au cas où un remoteJid complet arrive : « 212600000003@s.whatsapp.net »
    return cleaned.split("@")[0]


# ---------------------------------------------------------------------------
# 1. Création d'un RDV + planification 24h / 2h (en transaction)
# ---------------------------------------------------------------------------


def create_appointment_and_schedule(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    practitioner_id: uuid.UUID | None,
    wa_id: str,
    client_name: str | None,
    phone_e164: str | None,
    preferred_language: str,
    start_at: datetime,
    duration_min: int = 30,
    notes: str | None = None,
) -> tuple[models.Appointment, list[models.ReminderScheduled]]:
    """Crée le RDV + la file des rappels, tout en une transaction.

    Retourne (appointment, [reminders]). Idempotent grâce à la contrainte
    UNIQUE (appointment_id, type) : si un rappel 24h existe déjà pour ce RDV,
    l'INSERT lève une exception unique — l'appelant peut choisir d'ignorer.
    """
    # Récupérer ou créer le client (upsert léger sur wa_id)
    client = _get_or_create_client(db, tenant_id, wa_id, client_name, phone_e164, preferred_language)

    appointment = models.Appointment(
        tenant_id=tenant_id,
        practitioner_id=practitioner_id,
        client_id=client.id,
        start_at=start_at,
        duration_min=duration_min,
        status=models.AppointmentStatus.CONFIRMED,
        notes=notes,
    )
    db.add(appointment)
    # flush pour obtenir l'id sans commit (reste dans la transaction)
    db.flush()

    # Rappels planifiés UNIQUEMENT avec consentement explicite (loi 09-08 / RGPD).
    # Sans consentement : RDV confirmé sans rappels.
    reminders: list[models.ReminderScheduled] = []
    if client.consent_reminders_at is not None:
        reminders = [
            _schedule(db, appointment, models.ReminderType.REMINDER_24H, start_at - timedelta(hours=settings.reminder_24h_hours)),
            _schedule(db, appointment, models.ReminderType.REMINDER_2H, start_at - timedelta(hours=settings.reminder_2h_hours)),
        ]
    db.commit()
    db.refresh(appointment)
    return appointment, reminders


def _get_or_create_client(
    db: Session, tenant_id, wa_id, name, phone_e164, preferred_language
) -> models.Client:
    # Normalisation E.164 : on stocke SANS « + » (format des remoteJid Evolution API),
    # pour qu'un même patient ne soit jamais dupliqué entre webhook et API.
    wa_id = normalize_wa_id(wa_id)
    existing = db.scalar(
        select(models.Client).where(
            models.Client.tenant_id == tenant_id, models.Client.wa_id == wa_id
        )
    )
    if existing:
        if name and not existing.name:
            existing.name = name
        if phone_e164:
            existing.phone_e164 = phone_e164
        return existing
    client = models.Client(
        tenant_id=tenant_id,
        wa_id=wa_id,
        name=name,
        phone_e164=phone_e164,
        preferred_language=preferred_language or "fr",
    )
    db.add(client)
    db.flush()
    return client


def _schedule(
    db: Session, appointment: models.Appointment, rtype: models.ReminderType, send_at: datetime
) -> models.ReminderScheduled:
    r = models.ReminderScheduled(
        tenant_id=appointment.tenant_id,
        appointment_id=appointment.id,
        client_id=appointment.client_id,
        type=rtype,
        send_at=send_at,
        status=models.ReminderStatus.PENDING,
    )
    db.add(r)
    return r


def reschedule_appointment(
    db: Session,
    appointment: models.Appointment,
    new_start: datetime,
) -> list[models.ReminderScheduled]:
    """Déplace un RDV : met à jour la date, réactive les rappels 24h/2h sur la
    nouvelle date (contrainte UNIQUE(appointment_id, type) : on réutilise la
    ligne existante, jamais d'insertion en double) et repositionne les
    marqueurs d'idempotence pour permettre un nouvel envoi.

    Retourne les rappels planifiés (réactivés).
    """
    # 1) Mettre à jour le RDV + statut
    appointment.start_at = new_start
    appointment.status = models.AppointmentStatus.RESCHEDULED
    # Les rappels déjà envoyés sur l'ancienne date ne doivent pas bloquer les
    # nouveaux envois (un rappel 24h envoyé hier n'a plus de sens après déplacement)
    appointment.confirmation_sent_at = None
    appointment.reminder_24h_sent_at = None
    appointment.reminder_2h_sent_at = None

    # 2) Réactiver (ou créer) les rappels 24h / 2h sur la nouvelle date
    plan = [
        (models.ReminderType.REMINDER_24H, new_start - timedelta(hours=settings.reminder_24h_hours)),
        (models.ReminderType.REMINDER_2H, new_start - timedelta(hours=settings.reminder_2h_hours)),
    ]
    reminders: list[models.ReminderScheduled] = []
    for rtype, send_at in plan:
        existing = next((r for r in appointment.reminders if r.type == rtype), None)
        if existing:
            existing.status = models.ReminderStatus.PENDING
            existing.send_at = send_at
            existing.wamid = None
            existing.error_message = f"rescheduled to {new_start.isoformat()}"
            existing.attempts = 0
            existing.processed_at = None
            reminders.append(existing)
        else:
            reminders.append(_schedule(db, appointment, rtype, send_at))

    db.commit()
    db.refresh(appointment)
    logger.info(
        "RDV %s déplacé vers %s — %d rappels re-planifiés",
        appointment.id, new_start.isoformat(), len(reminders),
    )
    return reminders


# ---------------------------------------------------------------------------
# 2. Worker — sélection des rappels dus + envoi
# ---------------------------------------------------------------------------


def due_reminders(db: Session, now: datetime | None = None) -> list[models.ReminderScheduled]:
    """Sélectionne les rappels prêts à envoyer (ni opt-out, ni déjà envoyé)."""
    now = now or datetime.now(timezone.utc)
    stmt = (
        select(models.ReminderScheduled)
        .join(models.Client, models.Client.id == models.ReminderScheduled.client_id)
        .where(
            models.ReminderScheduled.status.in_(
                [models.ReminderStatus.PENDING, models.ReminderStatus.RETRYING]
            ),
            models.ReminderScheduled.send_at <= now,
            models.ReminderScheduled.attempts < models.ReminderScheduled.max_attempts,
            models.Client.opted_out_at.is_(None),  # JAMAIS de rappel à un patient "stop"
        )
        .limit(50)
    )
    return list(db.scalars(stmt).unique())


def send_due_reminders(db: Session) -> int:
    """Envoie tous les rappels dus. Retourne le nombre de rappels tentés.

    Idempotence (query + update atomique) :
    - la colonne reminder_X_sent_at du RDV n'est positionnée QUE si vide.
    - l'UPDATE du rappel passe par un WHERE status IN (pending, retrying).
    """
    sent = 0
    for r in due_reminders(db):
        try:
            _send_one(db, r)
            sent += 1
        except Exception:  # noqa: BLE001 — on attrape tout pour ne pas casser le worker
            _handle_failure(db, r)
        db.commit()
    return sent


def _send_one(db: Session, r: models.ReminderScheduled) -> None:
    appointment = r.appointment
    client = r.client
    tenant = r.tenant

    # Optimistic idempotence : on n'envoie que si ce rappel n'a pas déjà été marqué
    marker = appointment.reminder_sent(r.type)
    if marker is not None:
        _mark_skipped(db, r, f"already sent at {marker.isoformat()}")
        return

    text = _build_reminder_text(appointment, r.type)
    # Carte visuelle (design Kinayad) + texte en légende — expérience patient soignée
    card = None
    try:
        local_start = to_tenant_local(appointment.start_at, tenant)
        cabinet = appointment.practitioner.cabinet_name or appointment.practitioner.name if appointment.practitioner else "votre cabinet"
        card = cards.card_reminder_bytes(
            cabinet_name=cabinet,
            day=f"{_WEEKDAYS_FR[local_start.weekday()]} {local_start.strftime('%d/%m/%Y')}",
            time=local_start.strftime("%H:%M"),
            kind=_REMINDER_KIND.get(r.type, "Rappel"),
        )
    except Exception:  # noqa: BLE001 — la carte ne doit jamais casser l'envoi
        logger.exception("Génération carte rappel échouée (on envoie le texte seul)")

    # whatsapp.send_* gère lui-même le mode démo (aucun envoi réel).
    # Résilience : si l'image échoue, le texte du rappel part quand même.
    if card:
        try:
            message_id = whatsapp.send_media_reminder(tenant, client.wa_id, card, caption=text)
        except Exception:  # noqa: BLE001 — un rappel texte vaut mieux que rien
            logger.exception("Échec envoi carte rappel — repli sur le texte seul")
            message_id = whatsapp.send_text_reminder(tenant, client.wa_id, text)
    else:
        message_id = whatsapp.send_text_reminder(tenant, client.wa_id, text)
    _mark_sent(db, r, appointment, message_id)
    logger.info("Rappel %s envoyé -> %s (id=%s)", r.type.value, client.wa_id, message_id)


def _handle_failure(db: Session, r: models.ReminderScheduled) -> None:
    r.attempts += 1
    r.last_attempt_at = datetime.now(timezone.utc)
    if r.attempts >= r.max_attempts:
        r.status = models.ReminderStatus.FAILED
        logger.warning("Rappel %s marqué FAILED (max attempts)", r.id)
    else:
        r.status = models.ReminderStatus.RETRYING
        logger.warning("Rappel %s en cours de retry (attempt %s/%s)", r.id, r.attempts, r.max_attempts)


# ---------------------------------------------------------------------------
# Marqueurs
# ---------------------------------------------------------------------------


def _mark_sent(
    db: Session,
    r: models.ReminderScheduled,
    appointment: models.Appointment,
    wamid: str,
) -> None:
    r.status = models.ReminderStatus.SENT
    r.wamid = wamid
    r.processed_at = datetime.now(timezone.utc)
    now = datetime.now(timezone.utc)
    # Le marqueur sur le RDV devient la source d'idempotence principale
    if r.type == models.ReminderType.REMINDER_24H:
        appointment.reminder_24h_sent_at = now
    elif r.type == models.ReminderType.REMINDER_2H:
        appointment.reminder_2h_sent_at = now
    elif r.type == models.ReminderType.CONFIRMATION:
        appointment.confirmation_sent_at = now


def _mark_skipped(db: Session, r: models.ReminderScheduled, reason: str) -> None:
    r.status = models.ReminderStatus.SKIPPED
    r.error_message = reason
    r.processed_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Construction du texte du rappel (message libre — pas de template à faire approuver)
# ---------------------------------------------------------------------------


def _build_reminder_text(appointment: models.Appointment, rtype: models.ReminderType) -> str:
    p = appointment.practitioner
    cabinet = p.cabinet_name or p.name if p else "votre praticien"
    local_start = to_tenant_local(appointment.start_at, appointment.tenant)
    heure = local_start.strftime("%H:%M")
    date = local_start.strftime("%d/%m/%Y")
    language = appointment.client.preferred_language if appointment.client else "fr"

    if language in ("ar", "ar_MA"):
        if rtype == models.ReminderType.REMINDER_24H:
            return f"مرحبا! لديك موعد غدا الساعة {heure} في {cabinet}. للتأكيد أو التأجيل، أجب ببساطة على هذه الرسالة."
        if rtype == models.ReminderType.REMINDER_2H:
            return f"تذكير: موعدك اليوم الساعة {heure} في {cabinet}. يرجى تأكيد حضورك."
        return f"تم تأكيد الموعد يوم {date} الساعة {heure} في {cabinet}."

    if rtype == models.ReminderType.REMINDER_24H:
        return f"Bonjour ! RDV à {cabinet} demain à {heure}. Pour confirmer ou reporter, répondez simplement."
    if rtype == models.ReminderType.REMINDER_2H:
        return f"Rappel : votre RDV à {cabinet} est aujourd'hui à {heure}. Merci de confirmer votre présence."
    return f"RDV confirmé le {date} à {heure} chez {cabinet}."
