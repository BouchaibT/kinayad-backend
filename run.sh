#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Point d'entrée du service WEB Render.
# 1) Passe DATABASE_URL fournie par Render sous le bon dialecte psycopg.
# 2) Initialise la base + seed de démo (idempotent, sans danger en redéploy).
# 3) Lance l'API via uvicorn sur le port fourni par Render ($PORT).
# ---------------------------------------------------------------------------
set -euo pipefail

# Render fournit DATABASE_URL en postgres://...  → on s'assure du dialecte
# psycopg demandé par SQLAlchemy (postgresql+psycopg://...).
if [[ -n "${DATABASE_URL:-}" && "${DATABASE_URL}" != postgresql+psycopg://* ]]; then
  export DATABASE_URL="${DATABASE_URL/postgres:\/\//postgresql+psycopg://}"
fi

echo "==> Initialisation de la base + seed de démo (idempotent)"
python -m app.seed

echo "==> Démarrage de l'API sur 0.0.0.0:${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
