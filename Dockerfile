# Utiliser Python 3.13 slim pour une image légère
FROM python:3.13-slim

# Définir le répertoire de travail
WORKDIR /app

# Installer les dépendances système pour PostgreSQL
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copier les fichiers de dépendances
COPY requirements.txt .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code de l'application (nouvelle structure)
COPY run.py .
COPY app/ app/
COPY scripts/ scripts/

# Créer un utilisateur non-root pour la sécurité
RUN useradd -m -u 1000 appuser

# Créer les répertoires nécessaires et donner les permissions
RUN mkdir -p data/dumps logs && chown -R appuser:appuser /app

USER appuser

# Exposer le port 5000
EXPOSE 5000

# Variables d'environnement par défaut
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Commande de démarrage avec gunicorn pour la production
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "600", "--access-logfile", "-", "--error-logfile", "-", "run:app"]
