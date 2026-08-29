# ---------------------------------------------------------------------------
# Kinayad — image de production pour Render (API + Worker)
# On passe le role en argument build : web | worker
# ---------------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dépendances système minimales (psycopg[binary] embarque son runtime)
# fonts-dejavu-core : requis par app/services/cards.py (génération des cartes
# visuelles WhatsApp), absent de l'image de base python:3.11-slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Dépendances Python (cache Docker efficace)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif
COPY . .

# L'utilisateur non-root par défaut de Render est défini au runtime ;
# pas de port exposé fixe recommandé (Render choisit via $PORT).

# Par défaut : lance l'API via uvicorn ; le worker est lancé par un 2e service
# avec la commande "python -m app.worker" (voir render.yaml).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
