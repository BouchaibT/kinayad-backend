# -*- coding: utf-8 -*-
"""
Authentification dashboard — comptes praticiens par email + mot de passe.

- Mots de passe hachés avec bcrypt (jamais en clair).
- Sessions : tokens opaques révocables (le token brut n'est montré qu'une
  fois au login ; seul son hash SHA-256 est stocké). Durée de vie 30 jours.
- Chaque utilisateur est rattaché à UN tenant : l'isolation entre cabinets
  repose sur ce lien (vérifié par le middleware de chaque route).
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import settings

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash bcrypt (salt automatique)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: models.User) -> str:
    """Crée une session et retourne le token brut (montré UNE seule fois)."""
    token = secrets.token_urlsafe(32)
    session = models.Session(
        user_id=user.id,
        tenant_id=user.tenant_id,
        token_hash=_token_hash(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days),
    )
    db.add(session)
    db.commit()
    return token


def get_user_from_token(db: Session, token: str) -> models.User | None:
    """Retourne l'utilisateur d'un token valide (non expiré, non révoqué), ou None."""
    if not token:
        return None
    session = db.scalar(
        select(models.Session).where(models.Session.token_hash == _token_hash(token))
    )
    if not session:
        return None
    if session.revoked_at is not None:
        return None
    expires = session.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires is None or expires < datetime.now(timezone.utc):
        return None
    return session.user


def revoke_session(db: Session, token: str) -> bool:
    """Révoque une session (logout). Retourne True si une session a été révoquée."""
    session = db.scalar(
        select(models.Session).where(models.Session.token_hash == _token_hash(token))
    )
    if not session:
        return False
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Rate limiting simple (en mémoire — une seule instance Render)
# ---------------------------------------------------------------------------


class RateLimiter:
    """Limiteur simple : N tentatives par minute par clé (IP ou email)."""

    def __init__(self, limit: int | None = None):
        self.limit = limit if limit is not None else settings.login_rate_limit_per_minute
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic()
        window = [t for t in self._hits.get(key, []) if now - t < 60]
        if len(window) >= self.limit:
            self._hits[key] = window
            return False
        window.append(now)
        self._hits[key] = window
        return True


login_limiter = RateLimiter()
