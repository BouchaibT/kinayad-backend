# Kinayad — Backend (FastAPI + SQLAlchemy)

Micro-SaaS WhatsApp de RDV + rappels 24h/2h pour praticiens santé/beauté au Maroc.
Ce dépôt contient le **backend** : modèles SQLAlchemy, services rappels/webhook,
conversation WhatsApp par menus chiffrés, et routes FastAPI.

## Structure

```
kinayad-backend/
├── app/
│   ├── main.py                 # App FastAPI + router + /health
│   ├── config.py               # Settings Pydantic (env)
│   ├── worker.py               # Worker de rappels (polling)
│   ├── api/
│   │   ├── bookings.py         # POST /bookings (création RDV + planif rappels)
│   │   ├── webhook.py          # GET/POST /webhook (Meta, signature vérifiée)
│   │   ├── evolution_webhook.py# POST /webhook/evolution (messages WhatsApp réels)
│   │   ├── dashboard.py        # Lecture seule /public/dashboard/* (mot de passe)
│   │   ├── internal.py         # POST /internal/run-reminders (cron)
│   │   └── admin.py            # Création tenant + praticien + liaison Evolution
│   ├── db/
│   │   ├── models.py           # Tables SQLAlchemy (miroir schema.sql)
│   │   └── session.py          # engine + SessionLocal + get_db()
│   └── services/
│       ├── whatsapp.py         # Envoi via Evolution API (WhatsApp Web auto-hébergé)
│       ├── reminders.py        # Sélection/planification/envoi des rappels
│       ├── conversation.py     # ★ Menus à choix numérotés (patients non-lecteurs)
│       └── meta_webhook.py     # Parsing des événements Meta
├── tests/
│   ├── test_flow_evolution.py  # Parcours RDV complet via webhook Evolution
│   ├── test_flow_cancel_out.py # Annulation + opt-out + webhook Meta
│   └── test_dashboard_conversations.py
├── requirements.txt
└── README.md
```

## ★ Prise de RDV par choix numérotés (patients qui ne savent pas lire)

Beaucoup de patients au Maroc ne lisent pas mais utilisent WhatsApp tous les
jours. Kinayad ne leur demande JAMAIS d'écrire une phrase : le bot propose des
options numérotées, le patient répond par un chiffre.

```
Patient : « Bonjour docteur »          (ou n'importe quoi — le menu revient)
Bot     : 👋 Choisissez un chiffre :
          1️⃣ 📅 Prendre RDV   2️⃣ ❌ Annuler   3️⃣ 🕐 Horaires   0️⃣ 🚫 Arrêter
Patient : 1
Bot     : 📅 Choisissez un jour : 1️⃣ Lundi 31/08  2️⃣ Mardi 01/09 …
Patient : 1
Bot     : 📅 Créneaux : 1️⃣ 09:00  2️⃣ 09:30 …
Patient : 2
Bot     : ✅ Confirmez ? 1️⃣ Oui  2️⃣ Changer  3️⃣ Annuler
Patient : 1
Bot     : 🎉 RDV confirmé ! + rappels 24h/2h planifiés automatiquement
```

- Machine d'états persistée par patient (`conversation_states`) : IDLE → MENU →
  CHOOSING_DATE → CHOOSING_SLOT → CONFIRMING → RDV créé (ou CANCELLING).
- Bilingue FR / AR (détection automatique), emojis-pictogrammes pour les non-lecteurs.
- Créneaux générés depuis les heures d'ouverture du tenant
  (`tenant.settings["opening_hours"]`, défaut lun-ven 09h-12h / 14h-17h, pas de 30 min),
  créneaux déjà pris exclus, marge d'1h.
- Le même moteur est branché sur **les deux canaux** : webhook Evolution
  (WhatsApp Web réel) et webhook Meta.

## Canaux WhatsApp

| Canal | Entrant | Sortant | Coût |
|-------|---------|---------|------|
| **Evolution API** (recommandé, auto-hébergé) | `POST /webhook/evolution` | `EVOLUTION_API_URL` + `EVOLUTION_API_KEY` | gratuit (WhatsApp Web) |
| Meta Cloud API | `POST /webhook` | via `whatsapp.py` | payant par conversation |

En `DEMO_MODE=true`, aucun message n'est réellement envoyé : tout est journalisé
(dans `message_logs`, `event_type="outbound"`) et retourné — **coût de validation nul**.

## Lancer (dev)

```bash
cd kinayad-backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Base locale (Postgres) — ou passez DATABASE_URL
createdb kinayad
export DATABASE_URL=postgresql+psycopg://kinayad:kinayad@localhost:5432/kinayad
export DEMO_MODE=true            # simule les envois Meta (coût nul)

python -c "from app.db.session import init_db; init_db()"   # crée les tables

# API
uvicorn app.main:app --reload --port 8000

# Worker (dans un 2e terminal)
python -m app.worker
```

### Tester

```bash
# Health
curl http://localhost:8000/health

# Créer un RDV + planifier les rappels (transaction)
curl -X POST http://localhost:8000/bookings \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-kinayad" \
  -d '{
    "tenant_id": "<uuid tenant>",
    "wa_id": "+212612345678",
    "client_name": "Fatima",
    "preferred_language": "fr",
    "start_at": "2026-08-26T15:30:00+01:00",
    "duration_min": 30
  }'
```

## Notes phase 1

- En `DEMO_MODE=true`, aucun message n'est réellement envoyé : on journalise et on
  retourne un `wamid` factice → **coût de validation nul**.
- En production, désactivez `DEMO_MODE`, chiffrez le token (voir `whatsapp.py`)
  et validez la signature webhook avec l'App secret partagé.
- Privilégiez **Alembic** pour les migrations dès la 1ère prod (le prototype peut
  utiliser `Base.metadata.create_all`).
