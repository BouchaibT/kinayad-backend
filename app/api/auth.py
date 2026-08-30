# -*- coding: utf-8 -*-
"""
Routes d'authentification du dashboard — inscription, connexion, déconnexion.

- POST /auth/register : le médecin crée son cabinet + son compte (auto-login)
- POST /auth/login    : email + mot de passe → token opaque (30 jours)
- GET  /auth/me       : profil de l'utilisateur connecté
- POST /auth/logout   : révocation immédiate du token

Le middleware require_tenant_auth (utilisé par les routes dashboard) vérifie
que le token appartient au tenant du slug demandé : un compte ne peut JAMAIS
voir les données d'un autre cabinet.
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.db.session import get_db
from app.services import auth as auth_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "cabinet"


def get_token_from_header(authorization: str = Header(default="")) -> str:
    """Extrait le token du header 'Authorization: Bearer <token>'."""
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def require_tenant_auth(
    slug: str,
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> models.User:
    """Authentification + isolation : le user doit appartenir au tenant du slug.

    C'est LE point de sécurité du multi-cabinet : même avec un token valide,
    un utilisateur d'un autre cabinet est refusé (403).
    """
    token = get_token_from_header(authorization)
    user = auth_service.get_user_from_token(db, token) if token else None
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Compte désactivé")
    tenant = db.get(models.Tenant, user.tenant_id)
    if not tenant or tenant.slug != slug:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé pour ce cabinet")
    return user


def require_tenant_auth_me(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> models.User:
    """Authentification sans vérification de slug (pour /auth/me)."""
    token = get_token_from_header(authorization)
    user = auth_service.get_user_from_token(db, token) if token else None
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise")
    return user


# ---------------------------------------------------------------------------
# Schémas
# ---------------------------------------------------------------------------


class RegisterIn(BaseModel):
    cabinet_name: str = Field(..., min_length=2, max_length=120)
    practitioner_name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=128)


class UserOut(BaseModel):
    id: str
    email: str
    name: str | None
    tenant_id: str
    tenant_name: str
    tenant_slug: str


class AuthOut(BaseModel):
    token: str
    user: UserOut


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/register", response_model=AuthOut)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    """Inscription : crée le cabinet + le praticien + le compte, connecte direct."""
    email = payload.email.lower().strip()
    if db.scalar(select(models.User).where(models.User.email == email)):
        raise HTTPException(status_code=409, detail="Un compte existe déjà avec cet email")

    slug = _slugify(payload.cabinet_name)
    # Slug unique : suffixe si collision
    base = slug
    n = 2
    while db.scalar(select(models.Tenant).where(models.Tenant.slug == slug)):
        slug = f"{base}-{n}"
        n += 1

    tenant = models.Tenant(
        slug=slug,
        name=payload.cabinet_name.strip(),
        timezone="Africa/Casablanca",
        plan=models.TenantPlan.PRO,
        status=models.TenantStatus.ACTIVE,
        settings={},
    )
    db.add(tenant)
    db.flush()

    db.add(
        models.Practitioner(
            tenant_id=tenant.id,
            name=payload.practitioner_name.strip(),
            cabinet_name=payload.cabinet_name.strip(),
            is_active=True,
        )
    )

    user = models.User(
        tenant_id=tenant.id,
        email=email,
        password_hash=auth_service.hash_password(payload.password),
        name=payload.practitioner_name.strip(),
        is_active=True,
    )
    db.add(user)
    db.flush()

    token = auth_service.create_session(db, user)
    db.commit()
    logger.info("Nouveau cabinet inscrit : %s (%s) — user %s", slug, email, user.id)
    return AuthOut(token=token, user=_user_out(db, user, tenant))


@router.post("/login", response_model=AuthOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    """Connexion email + mot de passe → token opaque (30 jours)."""
    # Rate limiting par EMAIL, pas par IP : derrière le proxy Render (pas de
    # X-Forwarded-For géré), request.client.host est constant pour tous les
    # visiteurs — une limite par IP y ferait bloquer tous les cabinets dès
    # qu'UN seul compte reçoit trop de tentatives. Par email, seul le compte
    # ciblé est freiné, jamais les autres.
    email = payload.email.lower().strip()
    if not auth_service.login_limiter.allow(email):
        raise HTTPException(status_code=429, detail="Trop de tentatives — réessayez dans une minute")

    user = db.scalar(select(models.User).where(models.User.email == email))
    if not user or not auth_service.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé")

    token = auth_service.create_session(db, user)
    tenant = db.get(models.Tenant, user.tenant_id)
    logger.info("Connexion : %s (tenant %s)", email, tenant.slug if tenant else "?")
    return AuthOut(token=token, user=_user_out(db, user, tenant))


@router.get("/me", response_model=UserOut)
def me(user: models.User = Depends(require_tenant_auth_me), db: Session = Depends(get_db)):
    tenant = db.get(models.Tenant, user.tenant_id)
    return _user_out(db, user, tenant)


@router.post("/logout")
def logout(authorization: str = Header(default="")):
    token = get_token_from_header(authorization)
    if token:
        db = next(get_db())
        try:
            auth_service.revoke_session(db, token)
        finally:
            db.close()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_out(db: Session, user: models.User, tenant: models.Tenant | None) -> UserOut:
    return UserOut(
        id=str(user.id),
        email=user.email,
        name=user.name,
        tenant_id=str(user.tenant_id),
        tenant_name=tenant.name if tenant else "",
        tenant_slug=tenant.slug if tenant else "",
    )
