# -*- coding: utf-8 -*-
"""Sessions SQLAlchemy — une session par requête (dependency injection FastAPI)."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Crée les tables (phase 1 / prototypage local avec SQLite ou Postgres).
    Pour la prod, préférez des migrations versionnées (Alembic)."""
    from app import models  # noqa: PLC0415 — import tardif pour éviter cycle

    models.Base.metadata.create_all(bind=engine)
    _ensure_column("clients", "consent_reminders_at", "TIMESTAMP")


def _ensure_column(table: str, column: str, sql_type: str) -> None:
    """Migration légère : ajoute une colonne si elle n'existe pas (SQLite/Postgres).

    create_all ne modifie pas les tables existantes — cette vérification
    idempotente couvre l'ajout de colonnes sans introduire Alembic.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if column in {c["name"] for c in inspector.get_columns(table)}:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
    import logging

    logging.getLogger(__name__).info("Colonne %s.%s ajoutée (migration légère)", table, column)
