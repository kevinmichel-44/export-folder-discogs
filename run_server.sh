#!/bin/bash
# Script pour lancer le serveur Flask

cd "$(dirname "$0")"

# Activer l'environnement virtuel
source venv/bin/activate

# Vérifier que Flask est installé
if ! python -c "import flask" 2>/dev/null; then
    echo "❌ Flask n'est pas installé. Lancez: pip install -r requirements.txt"
    exit 1
fi

# Afficher le cache
echo ""
echo "==================================================================="
echo "  SERVEUR FLASK - BATCH EXPORT OPTIMISÉ"
echo "==================================================================="
echo ""

python -c "from database import DatabaseManager; db = DatabaseManager(); stats = db.get_cache_stats(); print(f'Cache actuel: {stats[\"total_cached\"]} releases')"

echo ""
echo "Démarrage du serveur..."
echo "URL: http://127.0.0.1:5000"
echo "Batch Export: http://127.0.0.1:5000/batch/list"
echo ""
echo "Appuyez sur Ctrl+C pour arrêter"
echo "==================================================================="
echo ""

# Lancer Flask
export FLASK_APP=run.py
export FLASK_ENV=development
python run.py
