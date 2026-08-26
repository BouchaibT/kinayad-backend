# -*- coding: utf-8 -*-
"""Configuration de Kinayad — chargée depuis les variables d'environnement."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Base de données ---
    database_url: str = "postgresql+psycopg://kinayad:kinayad@localhost:5432/kinayad"

    # --- Meta / WhatsApp Cloud API ---
    meta_graph_version: str = "v19.0"
    meta_api_url: str = "https://graph.facebook.com"
    # App partagée Kinayad (multi-tenant : chaque tenant a SON waba/phone/token)
    meta_app_id: str = ""
    meta_app_secret: str = ""
    webhook_verify_token: str = "change-me-kinayad"
    meta_verify_token: str = "kinayad_verify_change_me"  # GET webhook (Meta)
    meta_webhook_secret: str = "change_me_webhook"       # X-Hub-Signature-256 (POST)

    # --- Sécurité interne (API protégée / CORS) ---
    api_keys: list[str] = ["dev-secret-kinayad"]
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # --- Mot de passe du tableau de bord public (distinct des clés API internes) ---
    dashboard_password: str = ""

    # --- Evolution API (pont WhatsApp Web / Baileys auto-hébergé, pas l'API Meta) ---
    evolution_api_url: str = ""
    evolution_api_key: str = ""

    # --- Objets rappels (heures avant le RDV) ---
    reminder_24h_hours: int = 24
    reminder_2h_hours: int = 2

    # --- Worker ---
    worker_poll_interval_seconds: int = 15
    reminder_max_attempts: int = 3

    # --- Chiffrement du token (pour access_token_cipher) ---
    # Clé AES-256 (32 octets) en base64. Fournir via env CAMK_SECRET_KEY.
    encryption_key_b64: str = ""

    # --- Mode démo : n'appelle pas réellement l'API Meta ---
    demo_mode: bool = True
    demo_phone: str = "+212600000000"


settings = Settings()
