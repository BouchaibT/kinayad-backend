# -*- coding: utf-8 -*-
"""
ATTENTION : module obsolète.
Le point d'entrée DB canonique est `app.db.session` (engine, SessionLocal,
get_db, init_db). Ce fichier ne fait que re-exporter — conservé temporairement
pour rétrocompatibilité. Toute nouvelle écriture doit passer par `app.db.session`.
"""
from app.db.session import get_db, init_db, engine, SessionLocal  # noqa: F401
