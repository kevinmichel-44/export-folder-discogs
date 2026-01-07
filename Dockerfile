# Utiliser Python 3.11 slim pour une image légère
FROM python:3.11-slim

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers de dépendances
COPY requirements.txt .

# Installer les dépendances
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code de l'application
COPY app.py .
COPY templates/ templates/
COPY static/ static/

# Créer un utilisateur non-root pour la sécurité
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Exposer le port 5000
EXPOSE 5000

# Variables d'environnement par défaut
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1

# Commande de démarrage avec gunicorn pour la production
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "600", "app:app"]
