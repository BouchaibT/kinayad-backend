# -*- coding: utf-8 -*-
"""
App FastAPI principale (Kinayad).

Lancement (dev) :
    export DATABASE_URL=postgresql+psycopg://...:...@localhost:5432/kinayad
    export DEMO_MODE=true
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401  (charge les modèles)
from app.api import admin, auth, bookings, dashboard, evolution_webhook, internal, webhook
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Kinayad API",
    version="0.1.0",
    description="RDV WhatsApp + rappels 24h/2h pour praticiens (Maroc).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bookings.router)
app.include_router(auth.router)
app.include_router(webhook.router)
app.include_router(evolution_webhook.router)
app.include_router(internal.router)
app.include_router(dashboard.router)
app.include_router(admin.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "demo": settings.demo_mode}
