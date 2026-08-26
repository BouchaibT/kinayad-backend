# -*- coding: utf-8 -*-
"""
Seed de démonstration / environnement de dev Kinayad.

Remplit la base avec un tenant de démo, un praticien, plusieurs clients,
les templates WhatsApp de rappel, un RDV confirmé et sa file de rappels
(24h + 2h) planifiés — le tout en cohérence avec le reste du code.

Idempotent : re-exécutable sans erreur (il saute ce qui existe déjà).

Usage :
    python -m app.seed                 # crée les données de démo
    python -m app.seed --send          # crée PUIS tente d'envoyer les rappels dus
    python -m app.seed --reset         # supprime puis recrée (réinitialisation complète)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app import models
from app.config import settings
from app.db.session import SessionLocal, init_db
from app.services import reminders

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# --- Identifiants stables du tenant de démo (réutilisables en se/allant) ---
DEMO_SLUG = "demo-cabinet-rabat"
DEMO_PRACTITIONER = "Dr. Salma El Amrani"
DEMO_CLIENTS = [
    {"wa_id": "212600000001", "name": "Yasmine Bennani", "language": "fr"},
    {"wa_id": "212600000002", "name": "Omar Tazi", "language": "ar"},
]

# Templates WhatsApp de rappel (noms à créer dans la console Meta pour tester en prod).
TEMPLATES = [
    {"name": "confirmation_rdv", "language": "fr", "category": models.TemplateCategory.UTILITY},
    {"name": "confirmation_rdv_ar", "language": "ar", "category": models.TemplateCategory.UTILITY},
    {"name": "rappel_rdv_24h", "language": "fr", "category": models.TemplateCategory.UTILITY},
    {"name": "rappel_rdv_24h_ar", "language": "ar", "category": models.TemplateCategory.UTILITY},
    {"name": "rappel_rdv_2h", "language": "fr", "category": models.TemplateCategory.UTILITY},
    {"name": "rappel_rdv_2h_ar", "language": "ar", "category": models.TemplateCategory.UTILITY},
]


def _reset(db) -> None:
    """Réinitialise entièrement les tables de démo (utile pour re-seed propre)."""
    tables = [
        models.ReminderScheduled,
        models.Appointment,
        models.MessageLog,
        models.MetaTemplate,
        models.Client,
        models.Practitioner,
        models.InvoiceLine,
        models.Invoice,
        models.UsageMeta,
        models.AuditLog,
        models.Tenant,
    ]
    for t in tables:
        db.execute(delete(t))
    db.commit()
    logger.info("Base de démo réinitialisée (%s tables vidées).", len(tables))


def _get_or_create_tenant(db) -> models.Tenant:
    tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == DEMO_SLUG))
    if tenant:
        return tenant
    tenant = models.Tenant(
        slug=DEMO_SLUG,
        name="Cabinet de démonstration (Rabat)",
        timezone="Africa/Casablanca",
        plan=models.TenantPlan.PRO,
        status=models.TenantStatus.ACTIVE,
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=14),
        auto_refacture=True,
        settings={
            "webhook_configured": False,
            "demo": True,
        },
    )
    db.add(tenant)
    db.flush()
    logger.info("Tenant de démo créé : %s", DEMO_SLUG)
    return tenant


def _get_or_create_practitioner(db, tenant: models.Tenant) -> models.Practitioner:
    p = db.scalar(
        select(models.Practitioner).where(
            models.Practitioner.tenant_id == tenant.id,
            models.Practitioner.name == DEMO_PRACTITIONER,
        )
    )
    if p:
        return p
    p = models.Practitioner(
        tenant_id=tenant.id,
        name=DEMO_PRACTITIONER,
        profession="Dentiste",
        cabinet_name="Cabinet El Amrani",
        phone="+212600000000",
        email="salma.elamrani@example.com",
        greeting="Bonjour et bienvenue au Cabinet El Amrani. Nous confirmons et rappelons vos rendez-vous ici.",
        is_active=True,
    )
    db.add(p)
    db.flush()
    logger.info("Praticien de démo créé : %s", DEMO_PRACTITIONER)
    return p


def _seed_clients(db, tenant: models.Tenant) -> list[models.Client]:
    clients = []
    for c in DEMO_CLIENTS:
        client = db.scalar(
            select(models.Client).where(
                models.Client.tenant_id == tenant.id, models.Client.wa_id == c["wa_id"]
            )
        )
        if not client:
            client = models.Client(
                tenant_id=tenant.id,
                wa_id=c["wa_id"],
                name=c["name"],
                phone_e164=f"+{c['wa_id']}",
                preferred_language=c["language"],
                last_interaction_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
            db.add(client)
            logger.info("Client de démo créé : %s (%s)", c["name"], c["wa_id"])
        clients.append(client)
    db.flush()
    return clients


def _seed_templates(db, tenant: models.Tenant) -> None:
    for t in TEMPLATES:
        exists = db.scalar(
            select(models.MetaTemplate).where(
                models.MetaTemplate.tenant_id == tenant.id,
                models.MetaTemplate.name == t["name"],
                models.MetaTemplate.language == t["language"],
            )
        )
        if exists:
            continue
        body_spec = {"body": [{"type": "text", "text": "Exemple de corps de template."}]}
        db.add(
            models.MetaTemplate(
                tenant_id=tenant.id,
                name=t["name"],
                language=t["language"],
                category=t["category"],
                status=models.TemplateStatus.ACTIVE,
                version=1,
                body_spec=body_spec,
                last_checked_at=datetime.now(timezone.utc),
            )
        )
    db.flush()
    logger.info("Templates WhatsApp de démo synchronisés (%d définis).", len(TEMPLATES))


def _seed_invoice(db, tenant: models.Tenant) -> None:
    exists = db.scalar(
        select(models.Invoice).where(
            models.Invoice.tenant_id == tenant.id, models.Invoice.number == "DEMO-2026-0001"
        )
    )
    if exists:
        return
    from decimal import Decimal as D
    inv = models.Invoice(
        tenant_id=tenant.id,
        number="DEMO-2026-0001",
        status=models.InvoiceStatus.PAID,
        issued_at=datetime.now(timezone.utc) - timedelta(days=3),
        due_at=datetime.now(timezone.utc) + timedelta(days=24),
        plan_price_mad=D("599.00"),
        meta_cost_refacture_mad=D("0.00"),
        total_mad=D("599.00"),
        currency="MAD",
    )
    db.add(inv)
    db.flush()
    db.add(
        models.InvoiceLine(
            invoice_id=inv.id,
            description="Abonnement PRO — période de démo",
            quantity=D("1"),
            unit_price_mad=D("599.00"),
            subtotal_mad=D("599.00"),
        )
    )
    logger.info("Facture de démo créée : %s", inv.number)


def _seed_appointment(
    db, tenant: models.Tenant, practitioner: models.Practitioner, clients: list[models.Client]
) -> models.Appointment:
    """Crée un RDV confirmé dans ~3 jours (rappel 24h ~J-1, 2h le jour J)."""
    now = datetime.now(timezone.utc)
    start_at = (now + timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)

    existing = db.scalar(
        select(models.Appointment).where(
            models.Appointment.tenant_id == tenant.id,
            models.Appointment.client_id == clients[0].id,
            models.Appointment.start_at >= now,
        )
    )
    if existing:
        return existing

    appointment = models.Appointment(
        tenant_id=tenant.id,
        practitioner_id=practitioner.id,
        client_id=clients[0].id,
        start_at=start_at,
        duration_min=30,
        status=models.AppointmentStatus.CONFIRMED,
        notes="Seed automatique — démo.",
    )
    db.add(appointment)
    db.flush()

    # File de rappels planifiée (24h + 2h), via le service partagé.
    _ensure_reminder(db, appointment, models.ReminderType.REMINDER_24H, start_at - timedelta(hours=settings.reminder_24h_hours))
    _ensure_reminder(db, appointment, models.ReminderType.REMINDER_2H, start_at - timedelta(hours=settings.reminder_2h_hours))

    logger.info("RDV de démo créé le %s + rappels 24h/2h planifiés.", start_at.isoformat())
    return appointment


def _ensure_reminder(db, appointment, rtype, send_at) -> None:
    exists = db.scalar(
        select(models.ReminderScheduled).where(
            models.ReminderScheduled.appointment_id == appointment.id,
            models.ReminderScheduled.type == rtype,
        )
    )
    if not exists:
        db.add(
            models.ReminderScheduled(
                tenant_id=appointment.tenant_id,
                appointment_id=appointment.id,
                client_id=appointment.client_id,
                type=rtype,
                send_at=send_at,
                status=models.ReminderStatus.PENDING,
                max_attempts=settings.reminder_max_attempts,
            )
        )


def seed(reset: bool = False) -> None:
    """Point d'entrée du seed : init des tables puis données de démo."""
    init_db()
    db = SessionLocal()
    try:
        if reset:
            _reset(db)
        tenant = _get_or_create_tenant(db)
        practitioner = _get_or_create_practitioner(db, tenant)
        clients = _seed_clients(db, tenant)
        _seed_templates(db, tenant)
        _seed_invoice(db, tenant)
        _seed_appointment(db, tenant, practitioner, clients)
        db.commit()
        logger.info("Seed terminé avec succès (demo_mode=%s).", settings.demo_mode)
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed de démonstration Kinayad")
    parser.add_argument("--send", action="store_true", help="Tente aussi d'envoyer les rappels dus")
    parser.add_argument("--reset", action="store_true", help="Réinitialise puis re-seed")
    args = parser.parse_args(argv)

    seed(reset=args.reset)

    if args.send:
        db = SessionLocal()
        try:
            sent = reminders.send_due_reminders(db)
            logger.info("Rappels envoyés (démo): %d", sent)
        finally:
            db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
