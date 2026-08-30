# -*- coding: utf-8 -*-
"""
Test 5 — authentification multi-cabinet : inscription, connexion, ISOLATION.

Vérifie :
1. Inscription auto (register) → tenant + praticien + user + token
2. Connexion (login) → token opaque
3. /auth/me
4. **Isolation négative** : le token du cabinet A ne peut PAS accéder aux
   données du cabinet B (403)
5. Rate-limit sur /auth/login (429 après N tentatives)
6. Reset de mot de passe admin (ancien token révoqué, nouveau mdp OK)
7. Logout (token révoqué)

Usage : python tests/test_flow_auth.py  (API locale sur 127.0.0.1:8000)
"""
from __future__ import annotations

import sys
import time

import httpx
from sqlalchemy import select

API = "http://127.0.0.1:8000"


def main() -> int:
    print("=" * 60)
    print("TEST 5 — AUTH MULTI-CABINET + ISOLATION")
    print("=" * 60)

    # Nettoyage des données de test d'un run précédent (idempotence)
    sys.path.insert(0, ".")
    from app import models
    from app.db.session import SessionLocal

    db = SessionLocal()
    for slug in ("cabinet-alpha", "cabinet-beta"):
        t = db.scalar(select(models.Tenant).where(models.Tenant.slug == slug))
        if t:
            db.delete(t)
    db.commit()
    db.close()

    # --- 1. Inscription cabinet A ---
    r = httpx.post(f"{API}/auth/register", json={
        "cabinet_name": "Cabinet Alpha", "practitioner_name": "Dr. Alpha",
        "email": "alpha@kinayad.ma", "password": "motdepasseA123",
    })
    r.raise_for_status()
    a = r.json()
    assert a["token"] and a["user"]["tenant_slug"] == "cabinet-alpha"
    print(f"✅ 1. Inscription cabinet A : {a['user']['tenant_slug']} (token reçu)")

    # --- 2. Inscription cabinet B (isolation) ---
    r = httpx.post(f"{API}/auth/register", json={
        "cabinet_name": "Cabinet Beta", "practitioner_name": "Dr. Beta",
        "email": "beta@kinayad.ma", "password": "motdepasseB123",
    })
    r.raise_for_status()
    b = r.json()
    assert b["user"]["tenant_slug"] == "cabinet-beta"
    print(f"✅ 2. Inscription cabinet B : {b['user']['tenant_slug']}")

    # --- 3. /auth/me ---
    r = httpx.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {a['token']}"})
    r.raise_for_status()
    assert r.json()["email"] == "alpha@kinayad.ma"
    print("✅ 3. /auth/me OK")

    # --- 4. ISOLATION NÉGATIVE : token A → données du cabinet B → 403 ---
    r = httpx.get(f"{API}/public/dashboard/cabinet-beta/summary",
                  headers={"Authorization": f"Bearer {a['token']}"})
    print(f"✅ 4. Isolation : token A → tenant B → HTTP {r.status_code} (403 attendu)")
    assert r.status_code == 403
    r = httpx.get(f"{API}/public/dashboard/cabinet-alpha/summary",
                  headers={"Authorization": f"Bearer {a['token']}"})
    assert r.status_code == 200
    print("   token A → tenant A → HTTP 200 (accès légitime OK)")

    # --- 5. Reset admin : mot de passe + révocation des sessions ---
    r = httpx.post(f"{API}/auth/login", json={
        "email": "alpha@kinayad.ma", "password": "motdepasseA123",
    })
    r.raise_for_status()
    token_before = r.json()["token"]
    sys.path.insert(0, ".")
    from app import models
    from app.db.session import SessionLocal

    db = SessionLocal()
    user = db.scalar(select(models.User).where(models.User.email == "alpha@kinayad.ma"))
    user_id = str(user.id)
    db.close()

    r = httpx.post(f"{API}/admin/users/{user_id}/reset-password", headers={"X-API-Key": "dev-secret-kinayad"},
                   json={"new_password": "nouveauMDP456"})
    r.raise_for_status()
    print(f"✅ 5. Reset admin OK ({r.json()['status']})")

    # Ancien token révoqué
    r = httpx.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token_before}"})
    assert r.status_code == 401
    print("   ancien token révoqué → 401 ✅")
    # Nouveau mot de passe fonctionne
    r = httpx.post(f"{API}/auth/login", json={
        "email": "alpha@kinayad.ma", "password": "nouveauMDP456",
    })
    r.raise_for_status()
    token_new = r.json()["token"]
    print("   nouveau mot de passe → login OK ✅")

    # --- 6. Logout : révocation ---
    r = httpx.post(f"{API}/auth/logout", headers={"Authorization": f"Bearer {token_new}"})
    r.raise_for_status()
    r = httpx.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token_new}"})
    assert r.status_code == 401
    print("✅ 6. Logout → token révoqué (401)")

    # --- 7. Rate-limit sur login (en dernier : occupe le limiter du serveur) ---
    hits_429 = 0
    for _ in range(12):
        r = httpx.post(f"{API}/auth/login", json={
            "email": "alpha@kinayad.ma", "password": "mauvais-mot-de-passe",
        })
        if r.status_code == 429:
            hits_429 += 1
    print(f"✅ 7. Rate-limit : {hits_429} réponses 429 sur 12 tentatives")
    assert hits_429 >= 1

    print("\n🎉 TEST 5 — AUTH + ISOLATION VALIDÉ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
