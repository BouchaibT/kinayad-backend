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
