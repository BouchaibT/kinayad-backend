# Kinayad — Backend (FastAPI + SQLAlchemy)

Micro-SaaS WhatsApp de RDV + rappels 24h/2h pour praticiens santé/beauté au Maroc.
Ce dépôt contient le **backend** : modèles SQLAlchemy miroir du schéma SQL
(`schema.sql`), services rappels/webhook, et routes FastAPI.

## Structure

```
kinayad-backend/
├── app/
│   ├── main.py                 # App FastAPI + router + /health
│   ├── config.py               # Settings Pydantic (env)
│   ├── worker.py               # Worker de rappels (polling)
│   ├── api/
│   │   ├── bookings.py         # POST /bookings (création RDV + planif rappels)
│   │   └── webhook.py          # GET/POST /webhook (Meta, signature vérifiée)
│   ├── db/
│   │   ├── models.py           # 10 tables SQLAlchemy (miroir schema.sql)
│   │   └── session.py          # engine + SessionLocal + get_db()
│   └── services/
│       ├── whatsapp.py         # Envoi Cloud API Meta (chiffrement token, démo)
│       ├── reminders.py        # Sélection/planification/envoi des rappels
│       └── meta_webhook.py     # Parsing des événements Meta + opt-out
├── requirements.txt
└── README.md
```

## Modèles (10 tables)

Miroir fidèle du schéma SQL :

| Modèle | Table | Rôle |
|--------|-------|------|
| `Tenant` | `tenants` | WABA/Phone/Token chiffré, plan, timezone |
| `Practitioner` | `practitioners` | Multi-praticiens par cabinet |
| `Client` | `clients` | Identifié par `wa_id` E.164, opt-out |
| `Appointment` | `appointments` | RDV + marqueurs idempotence |
| `ReminderScheduled` | `reminders_scheduled` | File du worker |
| `MessageLog` | `message_logs` | Payload Meta brut (audit) |
| `MetaTemplate` | `meta_templates` | Statuts templates Meta |
| `Invoice` / `InvoiceLine` | `invoices` / `invoice_lines` | Facturation MAD |
| `UsageMeta` | `usage_meta` | Comptage conversations Meta |
| `AuditLog` | `audit_logs` | Traçabilité/compliance |

Points clés respectés depuis `schema.sql` :

- `tenant_id` FK sur **toutes** les tables métier (isolation).
- `UNIQUE(tenant_id, wa_id)` sur `clients` → un patient est unique PAR tenant.
- `UNIQUE(appointment_id, reminder_type)` sur `reminders_scheduled` → **idempotence**.
- Marqueurs `reminder_24h_sent_at` / `reminder_2h_sent_at` / `confirmation_sent_at`
  sur `appointments` = source d'idempotence de l'envoi.
- Statuts ENUM SQLAlchemy (`StatusType` / enum Python) portables PostgreSQL..

## Fichier de référence

- Schéma SQL d'origine : `kinayad-webhook/schema_kinayad.sql`

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
