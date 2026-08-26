# -*- coding: utf-8 -*-
"""
Worker de rappels — boucle de polling autonome.

Usage :
    python -m app.worker
"""
from __future__ import annotations

import logging
import time

from app import models  # noqa: F401  (assure le registre des modèles)
from app.db.session import SessionLocal
from app.services.reminders import send_due_reminders

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 15  # phase 1 : polling simple, largement suffisant (≤ 4 RDV en parallèle)


def run() -> None:
    logger.info("Worker de rappels démarré (poll toutes les %ss)", POLL_INTERVAL_SECONDS)
    while True:
        try:
            db = SessionLocal()
            try:
                sent = send_due_reminders(db)
                if sent:
                    logger.info("%s rappel(s) traité(s)", sent)
            finally:
                db.close()
        except Exception:  # noqa: BLE001 — le worker ne doit jamais mourir
            logger.exception("Erreur dans le cycle de polling")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
