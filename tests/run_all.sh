#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Batterie de tests Kinayad — parcours de bout en bout en local (démo).
#
# Prérequis : l'API doit tourner sur 127.0.0.1:8000 avec :
#   DATABASE_URL=sqlite:///./kinayad.db DEMO_MODE=true \
#   DASHBOARD_PASSWORD=kinayad-demo-2026 \
#   uvicorn app.main:app --host 127.0.0.1 --port 8000
#
# Usage :
#   bash tests/run_all.sh
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."
export DATABASE_URL="${DATABASE_URL:-sqlite:///./kinayad.db}"
export DEMO_MODE=true

echo "==> Remise à zéro de l'environnement de test"
python tests/setup_test_env.py >/dev/null

echo "==> TEST 1 — parcours patient complet (webhook Evolution)"
python tests/test_flow_evolution.py | tail -1

echo "==> TEST 2 — annulation + opt-out + webhook Meta"
python tests/test_flow_cancel_out.py | tail -1

echo "==> TEST 3 — conversations en cours (dashboard)"
python tests/test_dashboard_conversations.py >/dev/null && echo "OK"

echo "==> Batterie terminée"
