# -*- coding: utf-8 -*-
"""
Remise à zéro de l'environnement de test Kinayad.

Supprime la base SQLite, re-seed la démo, rattache l'instance Evolution et
le phone_number_id Meta au tenant de démo.

Usage :
    python tests/setup_test_env.py
    # puis relancer l'API et les tests
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")

from sqlalchemy import delete, select

from app import models
from app.db.session import SessionLocal, engine, init_db


def main() -> int:
    db_path = os.environ.get("DATABASE_URL", "sqlite:///./kinayad.db")
    print(f"Base : {db_path}")

    db = SessionLocal()
    try:
        # Vide TOUTES les tables (y compris conversation_states) dans l'ordre FK
        for table in reversed(models.Base.metadata.sorted_tables):
            db.execute(delete(table))
        db.commit()
        print("✅ Tables vidées")
    finally:
        db.close()

    # Re-seed (crée tenant, praticien, clients, templates, facture, RDV + rappels)
    from app import seed as seed_module

    seed_module.seed(reset=False)
    print("✅ Seed rejoué")

    # Rattachements webhook : instance Evolution + phone_number_id Meta
    db = SessionLocal()
    try:
        t = db.scalar(select(models.Tenant).where(models.Tenant.slug == "demo-cabinet-rabat"))
        s = dict(t.settings or {})
        s["evolution_instance"] = "kinayad-demo"
        s["evolution_instance_number"] = "212600000000"
        t.settings = s
        t.phone_number_id = 999999999
        db.commit()
        print(f"✅ Instance Evolution + phone_number_id rattachés ({t.slug})")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
