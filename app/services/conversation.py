# -*- coding: utf-8 -*-
"""
Service de conversation WhatsApp — menus à choix numérotés.

Objectif : permettre à un patient qui ne sait NI LIRE NI ÉCRIRE de prendre
rendez-vous en ne répondant que par des CHIFFRES. Le bot propose des options
numérotées (« Tapez 1 pour le matin, 2 pour l'après-midi… »), le patient
tape « 1 », « 2 », « 3 »… et le RDV se construit pas à pas, confirmé
automatiquement, avec les rappels 24h/2h planifiés.

Chaque option est préfixée d'un EMOJI-pictogramme (📅 ❌ 🕐 ✅) pour les
patients qui ne lisent pas du tout : le chiffre suffit, le picto aide.

Machine d'états (voir models.ConversationState) :
    IDLE → MENU → CHOOSING_DATE → CHOOSING_SLOT → CONFIRMING → (RDV créé) → IDLE
                     ↘ CANCELLING → (RDV annulé) → IDLE

Point d'entrée unique : handle_incoming_message() — utilisé par le webhook
Evolution (messages entrants WhatsApp Web) ET le webhook Meta.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.services import cards, whatsapp
from app.services.reminders import (
    create_appointment_and_schedule,
    normalize_wa_id,
    tenant_zoneinfo,
    to_tenant_local,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SESSION_TTL_MINUTES = 30          # au-delà, la conversation repart de zéro
MAX_SLOTS_PER_MENU = 9            # chiffres 1..9 — pas plus, sinon illisible
MAX_CANCEL_APPOINTMENTS = 5       # RDV annulables affichés en même temps
DEFAULT_OPENING_HOURS = {         # lundi → vendredi 09h-12h / 14h-17h
    "mon": [["09:00", "12:00"], ["14:00", "17:00"]],
    "tue": [["09:00", "12:00"], ["14:00", "17:00"]],
    "wed": [["09:00", "12:00"], ["14:00", "17:00"]],
    "thu": [["09:00", "12:00"], ["14:00", "17:00"]],
    "fri": [["09:00", "12:00"], ["14:00", "17:00"]],
}
APPOINTMENT_DURATION_MIN = 30

STOP_WORDS = {"stop", "arret", "arrêt", "quit", "0"}
_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")

_WEEKDAYS_FR = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi", 4: "Vendredi", 5: "Samedi", 6: "Dimanche"}
_WEEKDAYS_AR = {0: "الاثنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس", 4: "الجمعة", 5: "السبت", 6: "الأحد"}


# ---------------------------------------------------------------------------
# Point d'entrée unique
# ---------------------------------------------------------------------------


def handle_incoming_message(
    db: Session,
    *,
    tenant: models.Tenant,
    wa_id: str,
    text: str,
    push_name: str | None = None,
) -> str | None:
    """Traite un message entrant d'un patient et renvoie la réponse envoyée.

    Retourne le texte de la réponse (envoyée en réel ou journalisée en démo),
    ou None si rien n'a été envoyé (patient opt-out, message vide…).
    """
    wa_id = normalize_wa_id(wa_id)
    if not wa_id or not text:
        return None

    client = _get_or_create_client(db, tenant, wa_id, push_name)
    # JAMAIS de message à un patient qui a demandé l'arrêt
    if client.opted_out_at is not None:
        return None

    state = _get_or_create_state(db, tenant, client)
    _expire_if_stale(state)

    text = text.strip()
    reply_text, card = _dispatch(db, tenant, client, state, text)

    if reply_text:
        _send_reply(db, tenant, client, reply_text, card=card)
        client.last_interaction_at = datetime.now(timezone.utc)
        db.commit()
    return reply_text


# ---------------------------------------------------------------------------
# Machine d'états
# ---------------------------------------------------------------------------


def _dispatch(db, tenant, client, state, text: str) -> tuple[str | None, bytes | None]:
    """Retourne (texte_de_la_réponse, carte_image_optionnelle)."""
    lowered = text.lower()

    # Opt-out disponible depuis n'importe quel état
    if lowered in STOP_WORDS:
        _opt_out(db, tenant, client)
        state.state = "IDLE"
        state.context = {}
        return (_t(client, "🚫 Vous ne recevrez plus de messages. Pour revenir, écrivez-nous à tout moment. 👋",
                           "🚫 لن تصلك رسائل بعد الآن. للعودة، راسلنا في أي وقت. 👋"), None)

    # Un chiffre ? sinon on (re)propose le menu — TOUJOURS ramener au menu,
    # c'est la base d'une interface accessible sans lecture.
    if state.state in ("IDLE", "MENU"):
        return _handle_menu(db, tenant, client, state, text)
    if state.state == "CHOOSING_DATE":
        return _handle_date_choice(db, tenant, client, state, text)
    if state.state == "CHOOSING_SLOT":
        return _handle_slot_choice(db, tenant, client, state, text)
    if state.state == "CONFIRMING":
        return _handle_confirm_choice(db, tenant, client, state, text)
    if state.state == "CANCELLING":
        return _handle_cancel_choice(db, tenant, client, state, text)
    return _handle_menu(db, tenant, client, state, text)


def _handle_menu(db, tenant, client, state, text: str) -> tuple[str, bytes | None]:
    # Carte de bienvenue à CHAQUE affichage du menu principal : le patient voit
    # le design à chaque « Bonjour » / retour au menu, pas seulement au 1er contact.
    card = None
    try:
        card = cards.card_welcome_bytes(_cabinet_name(tenant, client))
    except Exception:  # noqa: BLE001 — la carte ne doit jamais casser la conversation
        logger.exception("Génération carte bienvenue échouée")

    if text in ("1", "2", "3", "4"):
        if text == "1":
            state.state = "CHOOSING_DATE"
            state.context = {}
            return (_menu_dates(db, tenant, client, state), None)
        if text == "2":
            upcoming = _upcoming_appointments(db, tenant, client.id, MAX_CANCEL_APPOINTMENTS)
            if not upcoming:
                state.state = "IDLE"
                return (_t(client, "📭 Vous n'avez aucun rendez-vous à annuler.",
                                  "📭 لا يوجد لديك أي موعد للإلغاء."), None)
            state.state = "CANCELLING"
            state.context = {"appointments": [str(a.id) for a in upcoming]}
            lines = [_t(client, "Quel rendez-vous voulez-vous annuler ?",
                               "أي موعد تريد إلغاءه؟")]
            for i, a in enumerate(upcoming, 1):
                lines.append(f"{i}️⃣ {_fmt_rdv(client, a)}")
            lines.append(_t(client, "0️⃣ ↩️ Revenir au menu", "0️⃣ ↩️ العودة للقائمة"))
            return ("\n".join(lines), None)
        if text == "3":
            state.state = "IDLE"
            return (_menu_hours(tenant, client), None)
        if text == "4":
            state.state = "IDLE"
            return (_menu_contact(db, tenant, client), None)
    # Entrée invalide / texte libre → on réaffiche le menu principal
    state.state = "IDLE"
    return (_menu_main(client), card)


def _handle_date_choice(db, tenant, client, state, text: str) -> tuple[str, bytes | None]:
    dates = _proposed_dates(tenant)
    if text.isdigit() and 1 <= int(text) <= len(dates):
        chosen = dates[int(text) - 1]
        slots = _available_slots(db, tenant, chosen)
        if not slots:
            state.state = "IDLE"
            return (_t(client, "😔 Aucun créneau disponible ce jour-là. Tapez 1 pour réessayer. 📅",
                              "😔 لا توجد مواعيد متاحة في هذا اليوم. اكتب 1 للمحاولة مجددًا. 📅"), None)
        state.state = "CHOOSING_SLOT"
        state.context = {
            "date": chosen.isoformat(),
            "slots": [s.isoformat() for s in slots],
        }
        day = _WEEKDAYS_FR[chosen.weekday()] if not _is_ar(client) else _WEEKDAYS_AR[chosen.weekday()]
        date_label = f"{day} {chosen.strftime('%d/%m')}"
        lines = [_t(client, f"📅 {date_label} — crénaux disponibles :",
                          f"📅 {date_label} — المواعيد المتاحة:")]
        for i, slot in enumerate(slots, 1):
            lines.append(f"{i}️⃣ {to_tenant_local(slot, tenant).strftime('%H:%M')}")
        lines.append(_t(client, "0️⃣ ↩️ Revenir", "0️⃣ ↩️ العودة"))
        return ("\n".join(lines), None)
    if text in ("0",):
        state.state = "IDLE"
        return (_menu_main(client), None)
    # Invalide → réafficher les dates
    return (_menu_dates(db, tenant, client, state), None)


def _handle_slot_choice(db, tenant, client, state, text: str) -> tuple[str, bytes | None]:
    if text in ("0",):
        state.state = "CHOOSING_DATE"
        return (_menu_dates(db, tenant, client, state), None)
    slots = state.context.get("slots") or []
    if text.isdigit() and 1 <= int(text) <= len(slots):
        chosen_iso = slots[int(text) - 1]
        state.context["slot"] = chosen_iso
        state.state = "CONFIRMING"
        start = datetime.fromisoformat(chosen_iso)  # UTC — stocké tel quel dans le contexte
        local_start = to_tenant_local(start, tenant)  # heure locale — affichage uniquement
        day = _WEEKDAYS_FR[local_start.weekday()] if not _is_ar(client) else _WEEKDAYS_AR[local_start.weekday()]
        cabinet = _cabinet_name(tenant, client)
        lines = [
            _t(client, "✅ Confirmez votre rendez-vous :",
                      "✅ تأكيد الموعد:"),
            f"🏥 {cabinet}",
            f"📅 {day} {local_start.strftime('%d/%m/%Y')}",
            f"⏰ {local_start.strftime('%H:%M')}",
            _t(client, "1️⃣ ✅ Oui, confirmer\n2️⃣ 🔄 Changer\n3️⃣ ❌ Annuler",
                      "1️⃣ ✅ نعم، تأكيد\n2️⃣ 🔄 تغيير\n3️⃣ ❌ إلغاء"),
        ]
        return ("\n".join(lines), None)
    return _handle_date_choice(db, tenant, client, state, "1")  # repartir sur les dates


def _handle_confirm_choice(db, tenant, client, state, text: str) -> tuple[str, bytes | None]:
    slot_iso = state.context.get("slot")
    if text == "1" and slot_iso:
        start = datetime.fromisoformat(slot_iso)
        practitioner = db.scalar(
            select(models.Practitioner).where(
                models.Practitioner.tenant_id == tenant.id,
                models.Practitioner.is_active.is_(True),
            ).order_by(models.Practitioner.created_at.asc()).limit(1)
        )
        appointment, reminders = create_appointment_and_schedule(
            db,
            tenant_id=tenant.id,
            practitioner_id=practitioner.id if practitioner else None,
            wa_id=client.wa_id,
            client_name=client.name,
            phone_e164=client.phone_e164,
            preferred_language=client.preferred_language,
            start_at=start,
            duration_min=APPOINTMENT_DURATION_MIN,
            notes="Pris via WhatsApp (menu chiffré).",
        )
        logger.info(
            "RDV %s confirmé par WhatsApp (client %s, tenant %s), %d rappels planifiés",
            appointment.id, client.wa_id, tenant.slug, len(reminders),
        )
        state.state = "IDLE"
        state.context = {}
        cabinet = _cabinet_name(tenant, client)
        local_start = to_tenant_local(start, tenant)  # affichage uniquement — start (UTC) déjà stocké au RDV
        day = _WEEKDAYS_FR[local_start.weekday()] if not _is_ar(client) else _WEEKDAYS_AR[local_start.weekday()]
        day_str = f"{day} {local_start.strftime('%d/%m/%Y')}"
        time_str = local_start.strftime("%H:%M")

        # Carte visuelle de confirmation (design Kinayad)
        card = None
        try:
            card = cards.card_confirm_bytes(cabinet, day_str, time_str, APPOINTMENT_DURATION_MIN)
        except Exception:  # noqa: BLE001 — la carte ne doit jamais casser la conversation
            logger.exception("Génération carte confirmation échouée")

        return (
            _t(
                client,
                f"🎉 RDV confirmé !\n🏥 {cabinet}\n📅 {day_str}\n⏰ {time_str}\n\n🔔 Rappels automatiques 24h et 2h avant. À bientôt !",
                f"🎉 تم تأكيد الموعد!\n🏥 {cabinet}\n📅 {day_str}\n⏰ {time_str}\n\n🔔 سنرسل لك تذكيرًا قبل الموعد بـ24 ساعة وساعتين. إلى اللقاء!",
            ),
            card,
        )
    if text == "2":
        state.state = "CHOOSING_DATE"
        state.context = {}
        return (_menu_dates(db, tenant, client, state), None)
    if text == "3":
        state.state = "IDLE"
        return (_menu_main(client), None)
    # Invalide → re-proposer la confirmation
    state.state = "CONFIRMING"
    return (_confirm_prompt(tenant, client, state), None)


def _handle_cancel_choice(db, tenant, client, state, text: str) -> tuple[str, bytes | None]:
    if text == "0":
        state.state = "IDLE"
        return (_menu_main(client), None)
    appointments = state.context.get("appointments") or []
    if text.isdigit() and 1 <= int(text) <= len(appointments):
        try:
            appt_id = uuid.UUID(appointments[int(text) - 1])
        except (ValueError, TypeError):
            appt_id = None
        appt = db.get(models.Appointment, appt_id) if appt_id else None
        if appt and appt.client_id == client.id and appt.tenant_id == tenant.id:
            appt.status = models.AppointmentStatus.CANCELLED
            appt.cancelled_at = datetime.now(timezone.utc)
            appt.cancel_reason = "patient_request"
            for r in appt.reminders:
                if r.status in (models.ReminderStatus.PENDING, models.ReminderStatus.RETRYING):
                    r.status = models.ReminderStatus.CANCELLED
            db.commit()
            logger.info("RDV %s annulé par le patient (WhatsApp)", appt.id)
            state.state = "IDLE"
            state.context = {}
            return (_t(client, "❌ Votre rendez-vous a été annulé.\n0️⃣ ↩️ Retour au menu",
                              "❌ تم إلغاء موعدك.\n0️⃣ ↩️ العودة للقائمة"), None)
    # Invalide → relister les RDV
    state.state = "CANCELLING"
    state.context = {"appointments": [str(a.id) for a in _upcoming_appointments(db, tenant, client.id, MAX_CANCEL_APPOINTMENTS)]}
    upcoming = _upcoming_appointments(db, tenant, client.id, MAX_CANCEL_APPOINTMENTS)
    lines = [_t(client, "Quel rendez-vous voulez-vous annuler ?",
                      "أي موعد تريد إلغاءه؟")]
    for i, a in enumerate(upcoming, 1):
        lines.append(f"{i}️⃣ {_fmt_rdv(client, a)}")
    lines.append(_t(client, "0️⃣ ↩️ Revenir au menu", "0️⃣ ↩️ العودة للقائمة"))
    return ("\n".join(lines), None)


# ---------------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------------


def _menu_main(client) -> str:
    if _is_ar(client):
        return (
            "👋 مرحبا! اختر رقمًا:\n"
            "1️⃣ 📅 حجز موعد\n"
            "2️⃣ ❌ إلغاء موعد\n"
            "3️⃣ 🕐 أوقات العمل\n"
            "4️⃣ 📞 الاتصال بالعيادة\n"
            "0️⃣ 🚫 إيقاف الرسائل"
        )
    return (
        "👋 Bonjour ! Choisissez un chiffre :\n"
        "1️⃣ 📅 Prendre RDV\n"
        "2️⃣ ❌ Annuler un RDV\n"
        "3️⃣ 🕐 Horaires du cabinet\n"
        "4️⃣ 📞 Contacter le cabinet\n"
        "0️⃣ 🚫 Arrêter les messages"
    )


def _menu_dates(db, tenant, client, state) -> str:
    dates = _proposed_dates(tenant)
    state.state = "CHOOSING_DATE"
    state.context = {}
    lines = [_t(client, "📅 Choisissez un jour :", "📅 اختر يومًا:")]
    for i, d in enumerate(dates, 1):
        if _is_ar(client):
            lines.append(f"{i}️⃣ {_WEEKDAYS_AR[d.weekday()]} {d.strftime('%d/%m')}")
        else:
            lines.append(f"{i}️⃣ {_WEEKDAYS_FR[d.weekday()]} {d.strftime('%d/%m')}")
    lines.append(_t(client, "0️⃣ ↩️ Retour", "0️⃣ ↩️ العودة"))
    return "\n".join(lines)


def _menu_hours(tenant, client) -> str:
    hours = (tenant.settings or {}).get("opening_hours") or DEFAULT_OPENING_HOURS
    lines = [_t(client, "🕐 Horaires du cabinet :", "🕐 أوقات عمل العيادة:")]
    if isinstance(hours, dict) and hours:
        labels = {"mon": "Lun", "tue": "Mar", "wed": "Mer", "thu": "Jeu", "fri": "Ven", "sat": "Sam", "sun": "Dim"}
        labels_ar = {"mon": "الاثنين", "tue": "الثلاثاء", "wed": "الأربعاء", "thu": "الخميس", "fri": "الجمعة", "sat": "السبت", "sun": "الأحد"}
        for key, ranges in hours.items():
            if not ranges:
                continue
            if _is_ar(client):
                label = labels_ar.get(key, key)
                lines.append(f"{label}: {'، '.join(f'{a} - {b}' for a, b in ranges)}")
            else:
                label = labels.get(key, key)
                lines.append(f"{label}: {' - '.join(f'{a}–{b}' for a, b in ranges)}")
    lines.append(_t(client, "0️⃣ ↩️ Retour", "0️⃣ ↩️ العودة"))
    return "\n".join(lines)


def _menu_contact(db, tenant, client) -> str:
    practitioner = db.scalar(
        select(models.Practitioner).where(
            models.Practitioner.tenant_id == tenant.id,
            models.Practitioner.is_active.is_(True),
        ).order_by(models.Practitioner.created_at.asc()).limit(1)
    )
    phone = practitioner.phone if practitioner else None
    if phone:
        return _t(client, f"📞 Pour joindre le cabinet : {phone}\n0️⃣ ↩️ Retour",
                         f"📞 للاتصال بالعيادة: {phone}\n0️⃣ ↩️ العودة")
    return _t(client, "📞 Appelez-nous sur WhatsApp pour toute question.\n0️⃣ ↩️ Retour",
                     "📞 اتصلوا بنا على واتساب لأي استفسار.\n0️⃣ ↩️ العودة")


# ---------------------------------------------------------------------------
# Créneaux & agenda
# ---------------------------------------------------------------------------


def _proposed_dates(tenant: models.Tenant, max_days: int = 4) -> list[date]:
    """Les prochains jours OUVRÉS à partir d'aujourd'hui (inclus), en heure locale du cabinet.

    « Aujourd'hui » doit être le jour du cabinet (Africa/Casablanca par défaut), pas
    celui du serveur — sinon un patient qui écrit tard le soir peut se voir proposer
    le mauvais jour selon où tourne le serveur (Render tourne en UTC).
    """
    today = datetime.now(tenant_zoneinfo(tenant)).date()
    dates: list[date] = []
    d = today
    while len(dates) < max_days and d <= today + timedelta(days=14):
        if d.weekday() < 5:  # lun → ven
            dates.append(d)
        d += timedelta(days=1)
    return dates


def _available_slots(db: Session, tenant: models.Tenant, day: date) -> list[datetime]:
    """Créneaux de 30 min libres pour un jour donné (heures d'ouverture du tenant)."""
    hours = (tenant.settings or {}).get("opening_hours") or DEFAULT_OPENING_HOURS
    weekday_key = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][day.weekday()]
    ranges = hours.get(weekday_key) if isinstance(hours, dict) else None
    if not ranges:
        return []

    # Les horaires d'ouverture ("09:00"-"12:00") sont exprimés en heure LOCALE du
    # cabinet (Africa/Casablanca par défaut) — jamais en UTC. Tout le calcul se fait
    # donc dans ce fuseau, et seul le résultat final (les créneaux retenus) est
    # reconverti en UTC, seul format que la base et le reste du code comprennent
    # (Appointment.start_at est un DateTime(timezone=True) stocké en UTC).
    tz = tenant_zoneinfo(tenant)
    day_start_local = datetime.combine(day, time.min, tzinfo=tz)
    day_end_local = day_start_local + timedelta(days=1)
    day_start_utc = day_start_local.astimezone(timezone.utc)
    day_end_utc = day_end_local.astimezone(timezone.utc)

    # RDV déjà pris ce jour-là (non annulés) → créneaux à exclure
    taken = db.scalars(
        select(models.Appointment).where(
            models.Appointment.tenant_id == tenant.id,
            models.Appointment.start_at >= day_start_utc,
            models.Appointment.start_at < day_end_utc,
            models.Appointment.status != models.AppointmentStatus.CANCELLED,
        )
    ).all()
    # Comparés en heure locale, dans le même fuseau que le curseur ci-dessous.
    taken_ranges = [
        (_as_utc(a.start_at).astimezone(tz), _as_utc(a.start_at).astimezone(tz) + timedelta(minutes=a.duration_min))
        for a in taken
    ]

    # Blocages ponctuels (vacances, urgence…) → créneaux à exclure aussi
    exceptions = db.scalars(
        select(models.AvailabilityException).where(
            models.AvailabilityException.tenant_id == tenant.id,
            models.AvailabilityException.start_at < day_end_utc,
            models.AvailabilityException.end_at > day_start_utc,
        )
    ).all()
    blocked_ranges = [
        ((_as_utc(e.start_at) or e.start_at).astimezone(tz),
         (_as_utc(e.end_at) or e.end_at).astimezone(tz))
        for e in exceptions
    ]

    now_local = datetime.now(tz)
    slots: list[datetime] = []
    for start_str, end_str in ranges:
        try:
            start = datetime.combine(day, time.fromisoformat(start_str), tzinfo=tz)
            end = datetime.combine(day, time.fromisoformat(end_str), tzinfo=tz)
        except ValueError:
            continue
        cursor = start
        while cursor + timedelta(minutes=APPOINTMENT_DURATION_MIN) <= end:
            slot_end = cursor + timedelta(minutes=APPOINTMENT_DURATION_MIN)
            if cursor >= now_local + timedelta(hours=1):  # marge d'au moins 1h
                if not any(_overlaps(cursor, slot_end, s, e) for s, e in taken_ranges + blocked_ranges):
                    slots.append(cursor.astimezone(timezone.utc))
                    if len(slots) >= MAX_SLOTS_PER_MENU:
                        return slots
            cursor += timedelta(minutes=APPOINTMENT_DURATION_MIN)
    return slots


def _overlaps(a1, a2, b1, b2) -> bool:
    return a1 < b2 and b1 < a2


def _upcoming_appointments(db, tenant, client_id, limit: int):
    now = datetime.now(timezone.utc)
    return list(db.scalars(
        select(models.Appointment)
        .where(
            models.Appointment.tenant_id == tenant.id,
            models.Appointment.client_id == client_id,
            models.Appointment.start_at >= now,
            models.Appointment.status != models.AppointmentStatus.CANCELLED,
        )
        .order_by(models.Appointment.start_at.asc())
        .limit(limit)
    ).unique())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_or_create_client(db, tenant, wa_id: str, push_name: str | None) -> models.Client:
    existing = db.scalar(
        select(models.Client).where(models.Client.tenant_id == tenant.id, models.Client.wa_id == wa_id)
    )
    if existing:
        if push_name and not existing.name:
            existing.name = push_name
            db.commit()
        return existing
    client = models.Client(
        tenant_id=tenant.id,
        wa_id=wa_id,
        name=push_name or None,
        phone_e164=f"+{wa_id}",
        preferred_language="ar" if push_name and _ARABIC_RE.search(push_name) else "fr",
    )
    db.add(client)
    db.flush()
    db.commit()
    logger.info("Nouveau patient %s (%s) — tenant %s", wa_id, push_name, tenant.slug)
    return client


def _get_or_create_state(db, tenant, client) -> models.ConversationState:
    state = db.scalar(
        select(models.ConversationState).where(
            models.ConversationState.tenant_id == tenant.id,
            models.ConversationState.client_id == client.id,
        )
    )
    if not state:
        state = models.ConversationState(
            tenant_id=tenant.id,
            client_id=client.id,
            state="IDLE",
            context={},
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=SESSION_TTL_MINUTES),
        )
        db.add(state)
        db.flush()
        db.commit()
    return state


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalise un datetime (naive = UTC) pour comparaison avec des aware."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _expire_if_stale(state) -> None:
    expires = _as_utc(state.expires_at)
    if expires is None or expires < datetime.now(timezone.utc):
        if state.state != "IDLE":
            logger.info("Conversation %s expirée (timeout) — retour à IDLE", state.client_id)
        state.state = "IDLE"
        state.context = {}
    state.expires_at = datetime.now(timezone.utc) + timedelta(minutes=SESSION_TTL_MINUTES)


def _opt_out(db, tenant, client) -> None:
    client.opted_out_at = datetime.now(timezone.utc)
    client.opted_out_reason = "user_stop"
    db.commit()
    logger.info("Opt-out patient %s (tenant %s)", client.wa_id, tenant.slug)


def _send_reply(db, tenant, client, text: str, card: bytes | None = None) -> str:
    """Envoie la réponse (carte visuelle optionnelle + texte) et la journalise.

    Résilience : si l'envoi de l'image échoue (réseau, proxy, API…), on replie
    sur le texte seul — un patient ne doit JAMAIS rester sans réponse.
    """
    try:
        if card:
            try:
                message_id = whatsapp.send_media_reminder(tenant, client.wa_id, card, caption=text)
            except Exception:  # noqa: BLE001 — repli : le texte seul vaut mieux que rien
                logger.exception("Échec envoi image à %s — repli sur le texte seul", client.wa_id)
                message_id = whatsapp.send_text_reminder(tenant, client.wa_id, text)
        else:
            message_id = whatsapp.send_text_reminder(tenant, client.wa_id, text)
    except Exception:  # noqa: BLE001 — ne jamais casser la conversation
        logger.exception("Échec d'envoi de la réponse à %s", client.wa_id)
        message_id = "failed"
    # Journal outbound → traçabilité + tests de bout en bout en mode démo
    db.add(
        models.MessageLog(
            tenant_id=tenant.id,
            meta_object="outbound_conversation",
            event_type="outbound",
            payload={"wa_id": client.wa_id, "text": text, "message_id": message_id, "has_card": bool(card)},
        )
    )
    db.commit()
    return message_id


def _confirm_prompt(tenant, client, state) -> str:
    start = to_tenant_local(datetime.fromisoformat(state.context.get("slot", "")), tenant)
    cabinet = _cabinet_name(tenant, client)
    lines = [
        _t(client, "✅ Confirmez votre rendez-vous :", "✅ تأكيد الموعد:"),
        f"🏥 {cabinet}",
        f"📅 {start.strftime('%d/%m/%Y')}",
        f"⏰ {start.strftime('%H:%M')}",
        _t(client, "1️⃣ ✅ Oui, confirmer\n2️⃣ 🔄 Changer\n3️⃣ ❌ Annuler",
                  "1️⃣ ✅ نعم، تأكيد\n2️⃣ 🔄 تغيير\n3️⃣ ❌ إلغاء"),
    ]
    return "\n".join(lines)


def _fmt_rdv(client, appointment) -> str:
    start = to_tenant_local(appointment.start_at, appointment.tenant)
    day = _WEEKDAYS_FR[start.weekday()] if not _is_ar(client) else _WEEKDAYS_AR[start.weekday()]
    return f"{day} {start.strftime('%d/%m')} à {start.strftime('%H:%M')}"


def _cabinet_name(tenant, client) -> str:
    if tenant is None:
        return "le cabinet"
    return tenant.name or "le cabinet"


def _is_ar(client) -> bool:
    return (client.preferred_language or "fr") in ("ar", "ar_MA")


def _t(client, fr: str, ar: str) -> str:
    return ar if _is_ar(client) else fr
