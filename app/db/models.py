# -*- coding: utf-8 -*-
"""
module obsolète (doublon) — conservé pour rétrocompatibilité.

Les modèles canoniques vivent dans `app/models.py` (module `app.models`).
Ce fichier re-exporte uniquement les noms réellement définis dans
`app.models`, de façon à rester importable sans erreur (`ImportError`).

Toute nouvelle écriture doit impérativement passer par `app.models`.
"""
from app.models import (  # noqa: F401
    Appointment,
    AppointmentStatus,
    AuditLog,
    AvailabilityException,
    Base,
    Client,
    ConversationState,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    MessageLog,
    MetaTemplate,
    Practitioner,
    ReminderScheduled,
    ReminderStatus,
    ReminderType,
    TemplateCategory,
    TemplateStatus,
    Tenant,
    TenantPlan,
    TenantStatus,
    TimestampMixin,
    UsageMeta,
)

__all__ = (
    "Appointment",
    "AppointmentStatus",
    "AuditLog",
    "AvailabilityException",
    "Base",
    "Client",
    "ConversationState",
    "Invoice",
    "InvoiceLine",
    "InvoiceStatus",
    "MessageLog",
    "MetaTemplate",
    "Practitioner",
    "ReminderScheduled",
    "ReminderStatus",
    "ReminderType",
    "TemplateCategory",
    "TemplateStatus",
    "Tenant",
    "TenantPlan",
    "TenantStatus",
    "TimestampMixin",
    "UsageMeta",
)
