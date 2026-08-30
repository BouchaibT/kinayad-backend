# -*- coding: utf-8 -*-
"""Helper de test — obtient un token dashboard pour le tenant de démo."""
import httpx

API = "http://127.0.0.1:8000"
EMAIL = "demo@kinayad.ma"
PASSWORD = "demo-password-123"


def dashboard_token(api: str = API) -> str:
    r = httpx.post(f"{api}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["token"]


def auth_headers(api: str = API) -> dict:
    return {"Authorization": f"Bearer {dashboard_token(api)}"}
