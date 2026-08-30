# -*- coding: utf-8 -*-
"""
Modèles SQLAlchemy de Kinayad — phase 1.

Mi­roir du schéma PostgreSQL défini dans `schema_kinayad.sql`.
Chaque table métier porte une FK `tenant_id` pour l'isolation multi-tenant.
Tous les timestamps sont stockés en UTC.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.mutable import MutableDict

# ---------------------------------------------------------------------------
# Base + mixin commun
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Base unique de tous les modèles (nouveau style SQLAlchemy 2.0)."""


class TimestampMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Enums (types ENUM PostgreSQL, alignés sur le schéma)
# ---------------------------------------------------------------------------


class TenantStatus(str, Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class TenantPlan(str, Enum):
    START = "start"          # 299 MAD/mois
    PRO = "pro"              # 599 MAD/mois
    BUSINESS = "business"    # 999 MAD/mois


class AppointmentStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class ReminderType(str, Enum):
    REMINDER_24H = "24h"
    REMINDER_2H = "2h"
    CONFIRMATION = "confirmation"


class ReminderStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    RETRYING = "retrying"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class TemplateStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    ACTIVE_LOW_QUALITY = "active_low_quality"
    PENDING_DISABLE = "pending_disable"
    PAUSED = "paused"
    DISABLED = "disabled"
    REJECTED = "rejected"


class TemplateCategory(str, Enum):
    UTILITY = "UTILITY"
    MARKETING = "MARKETING"
    AUTHENTICATION = "AUTHENTICATION"


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


# Alias générique : type VARCHAR + CHECK, compatible SQLite ET PostgreSQL
# (on neutralise le type ENUM natif PostgreSQL pour rester portable).
_enum_def = SAEnum


# ---------------------------------------------------------------------------
# tenants
# ---------------------------------------------------------------------------


class Tenant(TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)

    # Ressources WhatsApp dédiées au tenant (une App Meta partagée pour Kinayad)
    meta_app_id: Mapped[int | None] = mapped_column(BigInteger)
    waba_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    phone_number_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    access_token_cipher: Mapped[str | None] = mapped_column(Text)  # TOUJOURS chiffré

    timezone: Mapped[str] = mapped_column(
        Text, default="Africa/Casablanca", nullable=False, server_default="Africa/Casablanca"
    )

    plan: Mapped[TenantPlan] = mapped_column(
        _enum_def(TenantPlan, name="tenant_plan", values_callable=lambda x: [e.value for e in x]),
        default=TenantPlan.START,
        nullable=False,
        server_default="start",
    )
    status: Mapped[TenantStatus] = mapped_column(
        _enum_def(TenantStatus, name="tenant_status", values_callable=lambda x: [e.value for e in x]),
        default=TenantStatus.TRIAL,
        nullable=False,
        server_default="trial",
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_refacture: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    settings: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict, nullable=False, server_default="{}")

    # relations
    practitioners: Mapped[list["Practitioner"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    clients: Mapped[list["Client"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    reminders: Mapped[list["ReminderScheduled"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    templates: Mapped[list["MetaTemplate"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    usages: Mapped[list["UsageMeta"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["ConversationState"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    availability_exceptions: Mapped[list["AvailabilityException"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    users: Mapped[list["User"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# practitioners
# ---------------------------------------------------------------------------


class Practitioner(TimestampMixin, Base):
    __tablename__ = "practitioners"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_practitioner_tenant_name"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    profession: Mapped[str | None] = mapped_column(Text)
    cabinet_name: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    greeting: Mapped[str] = mapped_column(
        Text,
        default="Bonjour ! Bienvenue chez votre praticien. Nous rappelons votre rendez-vous lorsque nécessaire.",
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default="true")

    tenant: Mapped["Tenant"] = relationship(back_populates="practitioners")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="practitioner")


# ---------------------------------------------------------------------------
# clients (patients côté WhatsApp)
# ---------------------------------------------------------------------------


class Client(TimestampMixin, Base):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("tenant_id", "wa_id", name="uq_client_tenant_waid"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    wa_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    phone_e164: Mapped[str | None] = mapped_column(Text)
    preferred_language: Mapped[str] = mapped_column(
        Text, default="fr", nullable=False, server_default="fr"
    )
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opted_out_reason: Mapped[str | None] = mapped_column(Text)
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped["Tenant"] = relationship(back_populates="clients")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="client")
    reminders: Mapped[list["ReminderScheduled"]] = relationship(back_populates="client")
    conversation: Mapped["ConversationState | None"] = relationship(
        back_populates="client", cascade="all, delete-orphan", uselist=False
    )


# ---------------------------------------------------------------------------
# appointments
# ---------------------------------------------------------------------------


class Appointment(TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("duration_min BETWEEN 5 AND 240", name="ck_appointment_duration"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    practitioner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("practitioners.id")
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )

    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, default=30, nullable=False, server_default="30")
    status: Mapped[AppointmentStatus] = mapped_column(
        _enum_def(
            AppointmentStatus, name="appointment_status", values_callable=lambda x: [e.value for e in x]
        ),
        default=AppointmentStatus.PENDING,
        nullable=False,
        server_default="pending",
    )

    # rails d'idempotence (un seul envoi par type)
    confirmation_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_24h_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_2h_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    tenant: Mapped["Tenant"] = relationship(back_populates="appointments")
    practitioner: Mapped["Practitioner"] = relationship(back_populates="appointments")
    client: Mapped["Client"] = relationship(back_populates="appointments")
    reminders: Mapped[list["ReminderScheduled"]] = relationship(
        back_populates="appointment", cascade="all, delete-orphan"
    )

    def reminder_sent(self, reminder_type: ReminderType) -> datetime | None:
        """Retourne la date d'envoi du rappel pour ce type (idempotence).

        Utilisé par le worker : si une date est déjà positionnée, le rappel
        a déjà été envoyé (source d'idempotence) — on ne renvoie jamais deux fois.
        """
        if reminder_type == ReminderType.REMINDER_24H:
            return self.reminder_24h_sent_at
        if reminder_type == ReminderType.REMINDER_2H:
            return self.reminder_2h_sent_at
        if reminder_type == ReminderType.CONFIRMATION:
            return self.confirmation_sent_at
        return None

    def mark_reminder_sent(self, reminder_type: ReminderType, value: datetime) -> None:
        """Positionne le marqueur d'idempotence pour ce type de rappel."""
        if reminder_type == ReminderType.REMINDER_24H:
            self.reminder_24h_sent_at = value
        elif reminder_type == ReminderType.REMINDER_2H:
            self.reminder_2h_sent_at = value
        elif reminder_type == ReminderType.CONFIRMATION:
            self.confirmation_sent_at = value


# ---------------------------------------------------------------------------
# reminders_scheduled — la file du worker
# ---------------------------------------------------------------------------


class ReminderScheduled(TimestampMixin, Base):
    __tablename__ = "reminders_scheduled"
    __table_args__ = (
        UniqueConstraint("appointment_id", "type", name="uq_reminder_appointment_type"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )

    type: Mapped[ReminderType] = mapped_column(
        _enum_def(ReminderType, name="reminder_type", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ReminderStatus] = mapped_column(
        _enum_def(
            ReminderStatus, name="reminder_status", values_callable=lambda x: [e.value for e in x]
        ),
        default=ReminderStatus.PENDING,
        nullable=False,
        server_default="pending",
    )

    wamid: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False, server_default="3")
    error_message: Mapped[str | None] = mapped_column(Text)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped["Tenant"] = relationship(back_populates="reminders")
    appointment: Mapped["Appointment"] = relationship(back_populates="reminders")
    client: Mapped["Client"] = relationship(back_populates="reminders")


# ---------------------------------------------------------------------------
# message_logs — payload brut des webhooks Meta
# ---------------------------------------------------------------------------


class MessageLog(Base):
    __tablename__ = "message_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="SET NULL")
    )
    meta_object: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str | None] = mapped_column(Text)
    phone_number_id: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# meta_templates
# ---------------------------------------------------------------------------


class MetaTemplate(TimestampMixin, Base):
    __tablename__ = "meta_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "language", name="uq_template_tenant_name_lang"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    meta_template_id: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, default="fr", nullable=False, server_default="fr")
    category: Mapped[TemplateCategory] = mapped_column(
        _enum_def(
            TemplateCategory, name="template_category", values_callable=lambda x: [e.value for e in x]
        ),
        default=TemplateCategory.UTILITY,
        nullable=False,
        server_default="UTILITY",
    )
    status: Mapped[TemplateStatus] = mapped_column(
        _enum_def(
            TemplateStatus, name="template_status", values_callable=lambda x: [e.value for e in x]
        ),
        default=TemplateStatus.PENDING_APPROVAL,
        nullable=False,
        server_default="pending_approval",
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, server_default="1")
    body_spec: Mapped[dict] = mapped_column(JSON, nullable=False)
    quality_rating: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped["Tenant"] = relationship(back_populates="templates")


# ---------------------------------------------------------------------------
# billing
# ---------------------------------------------------------------------------


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("tenant_id", "number", name="uq_invoice_tenant_number"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        _enum_def(InvoiceStatus, name="invoice_status", values_callable=lambda x: [e.value for e in x]),
        default=InvoiceStatus.DRAFT,
        nullable=False,
        server_default="draft",
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan_price_mad: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False, server_default="0")
    meta_cost_refacture_mad: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=0, nullable=False, server_default="0"
    )
    total_mad: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False, server_default="0")

    currency: Mapped[str] = mapped_column(Text, default="MAD", nullable=False, server_default="MAD")
    tva_status: Mapped[str] = mapped_column(
        Text, default="non_applicable_art259-1", nullable=False, server_default="non_applicable_art259-1"
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="invoices")
    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class InvoiceLine(TimestampMixin, Base):
    __tablename__ = "invoice_lines"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=1, nullable=False, server_default="1")
    unit_price_mad: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False, server_default="0")
    subtotal_mad: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False, server_default="0")

    invoice: Mapped["Invoice"] = relationship(back_populates="lines")


# ---------------------------------------------------------------------------
# usage_meta — conversations facturées par Meta (pour la refacturation)
# ---------------------------------------------------------------------------


class UsageMeta(Base):
    __tablename__ = "usage_meta"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "period_month", "conversation_type", "category", "country_code",
            name="uq_usage_meta_line",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    conversation_type: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[str] = mapped_column(Text, default="MA", nullable=False, server_default="MA")
    conversations: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0, nullable=False, server_default="0")
    cost_mad: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False, server_default="0")

    tenant: Mapped["Tenant"] = relationship(back_populates="usages")


# ---------------------------------------------------------------------------
# audit_logs
# ---------------------------------------------------------------------------


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="SET NULL")
    )
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)  # system | user | admin
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# conversation_states — machine d'états des conversations WhatsApp (menus chiffrés)
# ---------------------------------------------------------------------------


class ConversationState(TimestampMixin, Base):
    """État de conversation d'un patient avec le bot (menus à choix numérotés).

    Permet à un patient qui ne sait ni lire ni écrire de prendre RDV en ne
    répondant que par des CHIFFRES : le bot propose des options numérotées,
    le patient tape « 1 », « 2 », « 3 »… et le RDV se construit pas à pas.

    États (state) :
      IDLE            — pas de conversation en cours (menu renvoyé à tout message)
      MENU            — menu principal affiché (on attend un choix)
      CHOOSING_DATE   — on attend le chiffre du jour souhaité
      CHOOSING_SLOT   — on attend le chiffre du créneau souhaité
      CONFIRMING      — on attend la confirmation (1 = oui / 2 = non / 3 = annuler)
      CANCELLING      — on attend le chiffre du RDV à annuler

    `context` (JSON) porte les données intermédiaires (date proposée, créneaux…).
    `expires_at` : au-delà, la conversation repart de zéro (timeout).
    """

    __tablename__ = "conversation_states"
    __table_args__ = (
        UniqueConstraint("tenant_id", "client_id", name="uq_conversation_tenant_client"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(Text, default="IDLE", nullable=False, server_default="IDLE")
    context: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict, nullable=False, server_default="{}")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped["Tenant"] = relationship(back_populates="conversations")
    client: Mapped["Client"] = relationship(back_populates="conversation")


# ---------------------------------------------------------------------------
# availability_exceptions — blocages ponctuels de l'agenda du praticien
# ---------------------------------------------------------------------------


class AvailabilityException(TimestampMixin, Base):
    """Absence ponctuelle du praticien (vacances, urgence, formation…).

    Intervalle [start_at, end_at) en UTC pendant lequel AUCUN créneau n'est
    proposé au patient. Géré depuis le dashboard praticien (aucune
    reconfiguration des heures d'ouverture nécessaire).
    """

    __tablename__ = "availability_exceptions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)

    tenant: Mapped["Tenant"] = relationship(back_populates="availability_exceptions")


# ---------------------------------------------------------------------------
# users — comptes praticiens (email + mot de passe), distincts des praticiens
# ---------------------------------------------------------------------------


class User(TimestampMixin, Base):
    """Compte de connexion au dashboard (email + mot de passe haché).

    Distinct de Practitioner : un cabinet peut avoir plusieurs utilisateurs
    (médecin fondateur, secrétaire, associé…). Chaque user est rattaché à UN
    tenant — l'isolation des données repose sur ce lien.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_user_email"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default="true")

    tenant: Mapped["Tenant"] = relationship(back_populates="users")
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# sessions — tokens opaques révocables (pas de JWT : révocation immédiate)
# ---------------------------------------------------------------------------


class Session(TimestampMixin, Base):
    """Session de connexion : hash du token + tenant + expiration.

    Le token brut n'est montré qu'UNE fois au login (renvoyé au client) ;
    seul son hash SHA-256 est stocké. Révocable immédiatement (logout ou
    suppression de la ligne). Durée de vie : 30 jours (config).
    """

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="sessions")
    tenant: Mapped["Tenant"] = relationship(back_populates="sessions")
