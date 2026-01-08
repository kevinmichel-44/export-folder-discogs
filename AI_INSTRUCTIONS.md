# Instructions IA - Export Folder Discogs

## Description du Projet

Application Flask pour exporter des collections et des listings marketplace depuis l'API Discogs. Le projet utilise OAuth pour l'authentification et implémente un système de cache SQLite pour optimiser les performances et contourner les limitations de rate limiting de l'API Discogs.

## Architecture Technique

### Stack Technologique
- **Framework Web**: Flask 3.0.0
- **Client API**: discogs-client 2.3.0
- **ORM**: SQLAlchemy 2.0.45
- **Base de données**: SQLite (discogs_cache.db)
- **Authentification**: OAuth 1.0a (Discogs)
- **Runtime**: Python 3.13

### Structure des Fichiers Principaux

```
export-folder-discogs/
├── app.py                    # Application Flask principale
├── database.py               # Modèles SQLAlchemy et gestionnaire de cache
├── init_db.py               # Script d'initialisation de la base de données
├── import_collection.py     # Script CLI pour import manuel du cache
├── requirements.txt         # Dépendances Python
├── .env                     # Variables d'environnement (OAuth credentials)
├── discogs_cache.db        # Base de données SQLite du cache
├── templates/
│   ├── folders.html        # Page principale - liste des dossiers collection
│   ├── marketplace.html    # Export des listings marketplace
│   └── import_cache.html   # Interface d'import du cache
└── docs/
    ├── CACHE_README.md     # Documentation du système de cache
    └── IMPORT_MANUAL.md    # Guide d'import manuel
```

## Fonctionnalités Principales

### 1. Authentification Discogs (OAuth)
- **Route**: `/` - Redirection vers l'authentification OAuth
- **Route**: `/callback` - Callback OAuth après autorisation
- **Credentials**: Stockés dans `.env` (CONSUMER_KEY, CONSUMER_SECRET)
- **Session**: Tokens OAuth stockés en session Flask

### 2. Export Collection
- **Route**: `/folders` - Liste des dossiers de collection
- **Route**: `/export/<folder_id>` - Lance l'export d'un dossier
- **Route**: `/progress/<export_id>` - SSE pour progression en temps réel
- **Format**: CSV avec colonnes : Artists, Title, Label, Catalog Number, Country, Year, Genres, Styles, Price, URL
- **Rate Limiting**: 1.1s entre chaque appel API (limite : 60 req/min)
- **Cache**: Vérifie d'abord le cache SQLite avant d'appeler l'API

### 3. Export Marketplace
- **Route**: `/marketplace` - Page d'export des listings
- **Route**: `/export_marketplace` - Lance l'export
- **Route**: `/progress_marketplace/<export_id>` - SSE pour progression
- **Format**: CSV avec informations de vente (prix, état, commentaires, etc.)

### 4. Système de Cache
- **Base de données**: SQLite avec table `cached_releases`
- **Expiration**: 30 jours (configurable dans `database.py`)
- **Stratégie**: 
  - Vérifie le cache avant chaque appel API
  - Stocke automatiquement chaque release récupérée
  - Statistiques de cache disponibles (total, dernière semaine)

### 5. Import Cache Pré-chargé
- **Interface Web**: `/import_cache` - Sélection de dossiers à pré-charger
- **Endpoint API**: `/start_import` (POST) - Lance l'import en arrière-plan
- **Progression**: `/progress_import` (SSE) - Suivi en temps réel
- **CLI Alternative**: `python import_collection.py` pour import manuel

## Détails d'Implémentation

### Gestion du Rate Limiting

```python
# Délai entre les requêtes API
time.sleep(1.1)  # 1.1 secondes = safe pour 60 req/min

# Retry avec backoff exponentiel
max_retries = 3
retry_delay = 5  # 5s, 10s, 15s
```

### Structure du Cache

```python
class CachedRelease(Base):
    id = Column(Integer, primary_key=True)        # Discogs release_id
    title = Column(String(500))
    artists = Column(Text)
    labels = Column(Text)
    catno = Column(Text)
    country = Column(String(100))
    year = Column(String(10))
    genres = Column(Text)
    styles = Column(Text)
    price = Column(String(50))
    url = Column(Text)
    raw_data = Column(Text)                       # JSON complet pour usage futur
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
```

### Session Context pour Background Tasks

**Problème**: Flask session n'est pas accessible dans les threads background
**Solution**: Extraire les tokens avant de lancer le thread

```python
# CORRECT - Dans app.py
access_token = session.get('access_token')
access_secret = session.get('access_secret')

def run_import():
    # Utiliser access_token et access_secret directement
    d = discogs_client.Client(user_agent, 
                              consumer_key=consumer_key,
                              consumer_secret=consumer_secret,
                              token=access_token,
                              secret=access_secret)
```

### Logging Structure

Tous les logs sont préfixés pour faciliter le filtrage:
- `[COLLECTION]` - Logs d'export de collection
- `[MARKETPLACE]` - Logs d'export marketplace
- `[IMPORT]` - Logs d'import de cache
- `[DB]` - Logs de base de données

Progression logguée tous les 25 items:
```python
if idx % 25 == 0 or idx == 1:
    print(f"[COLLECTION] Processing release {idx}/{total_releases} (cache hits: {cache_hits}, API calls: {api_calls})")
```

## Variables d'Environnement

Fichier `.env` requis:
```bash
CONSUMER_KEY=your_discogs_consumer_key
CONSUMER_SECRET=your_discogs_consumer_secret
SECRET_KEY=your_flask_secret_key
DATABASE_URL=sqlite:///discogs_cache.db  # Optionnel, valeur par défaut
```

## Commandes Utiles

### Installation
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Initialisation Base de Données
```bash
python init_db.py
```

### Import Manuel CLI
```bash
python import_collection.py
```

### Lancement Serveur
```bash
python app.py
# Ou en production:
gunicorn app:app
```

## Points d'Attention pour l'IA

### 1. Ne JAMAIS modifier sans précaution
- Les délais de rate limiting (1.1s minimum)
- La logique d'extraction des tokens avant threading
- Les indices de base de données (release_id)
- La structure des colonnes CSV (ordre important pour compatibilité)

### 2. Optimisations Possibles
- Batch processing pour les inserts DB (actuellement un par un)
- Compression des données raw_data (JSON peut être volumineux)
- Index supplémentaires sur updated_at pour queries de statistiques
- Pool de connexions pour SQLAlchemy (actuellement NullPool)

### 3. Limitations Connues
- L'API Discogs ne fournit pas `date_changed` dans les listes de collection
- Le cache ne peut pas détecter automatiquement les modifications de releases
- SQLite peut avoir des problèmes de concurrence si multiples exports simultanés
- Les SSE ne fonctionnent pas derrière tous les proxies/load balancers

### 4. Sécurité
- Les tokens OAuth sont en session (pas persistés en DB)
- SECRET_KEY Flask doit être aléatoire et sécurisé en production
- Pas de validation CSRF actuellement (à ajouter si nécessaire)
- Les exports CSV ne sont pas stockés (générés à la volée)

## Système de Batch Processing (Optimisé)

### Nouveaux Fichiers
- `batch_processor.py` - Worker pool avec Token Bucket algorithm
- `batch_flask_integration.py` - Intégration Flask pour batch processing
- `test_batch_processor.py` - Tests et benchmarks

### Architecture du Batch Processor

Le système de batch processing optimise les exports avec :

1. **Token Bucket Algorithm** pour rate limiting fluide
2. **Worker Pool** avec file de priorité
3. **Processing parallèle** des items en cache
4. **Retry automatique** avec backoff exponentiel

### Components

#### TokenBucket
Gère le rate limiting de manière fluide au lieu de délais fixes.

```python
bucket = TokenBucket(capacity=60, refill_rate=1.0)  # 60 req/min
bucket.wait_for_token(1)  # Bloque jusqu'à disponibilité
```

**Avantages vs délais fixes** :
- Permet les bursts initiaux (utilise tokens accumulés)
- Lissage automatique sur la durée
- Pas de "gaspillage" de temps si tokens disponibles

#### WorkerPool
File de workers avec priorités et statistiques.

```python
pool = WorkerPool(num_workers=3, rate_limit_capacity=60)
pool.start(discogs_client, db_manager)
pool.add_task(release_id=123, priority=1, callback=on_result)
pool.stop(wait=True)
stats = pool.get_stats()  # cache_hits, api_calls, retries, etc.
```

**Features** :
- PriorityQueue pour tâches importantes en premier
- Parallélisation des lectures cache (pas de rate limit)
- Monitoring temps réel (total, completed, failed, etc.)
- Retry intelligent avec exponential backoff

#### BatchProcessor
Interface haut niveau pour processing simplifié.

```python
processor = BatchProcessor(client, db, num_workers=3)
stats = processor.process_releases(release_ids, callback=my_callback)
```

### Intégration Flask

Le fichier `batch_flask_integration.py` fournit des endpoints optimisés :

```python
from batch_flask_integration import create_batch_blueprint

batch_bp = create_batch_blueprint(app)
app.register_blueprint(batch_bp)
```

**Nouveaux endpoints** :
- `POST /batch/export/<folder_id>` - Lance export optimisé
- `GET /batch/progress/<batch_id>` - SSE progression temps réel
- `GET /batch/download/<batch_id>` - Télécharge CSV
- `GET /batch/status/<batch_id>` - Status JSON
- `POST /batch/cancel/<batch_id>` - Annule job
- `GET /batch/list` - Liste tous les jobs

### Performance Comparison

**Approche Séquentielle (Original)** :
- 100 releases × 1.1s = 110 secondes
- Pas de parallélisation
- Délais fixes même si cache disponible

**Approche Batch (Optimisée)** :
- Avec 3 workers et 50% cache hit :
  - 50 releases du cache : ~0.5s (parallèle)
  - 50 API calls : ~50s (rate limited)
  - **Total : ~50s (2.2x plus rapide)**

Avec meilleur cache (80% hit rate) :
- 80 releases du cache : ~0.8s
- 20 API calls : ~20s
- **Total : ~20s (5.5x plus rapide)**

### Tests et Benchmarks

Lancer les tests :
```bash
python test_batch_processor.py
```

Tests inclus :
- Token Bucket algorithm
- Worker pool simple
- Comparaison performance théorique
- Benchmark cache reads
- Exemples d'utilisation

## Évolutions Futures Envisageables

1. **Cache Intelligent**: Système de rafraîchissement sélectif basé sur l'âge du cache
2. **Export Formats**: Support JSON, XML en plus du CSV
3. **Filtres Avancés**: Par genre, année, label lors de l'export
4. **API REST**: Endpoints pour intégrations tierces
5. **Statistiques**: Dashboard avec graphiques de collection
6. **Multi-utilisateurs**: Support de plusieurs comptes Discogs
7. **Background Jobs**: Utiliser Celery/RQ au lieu de threading simple ✅ (Batch processor implémenté)
8. **Tests**: Suite de tests unitaires et d'intégration

## Débogage

### Erreurs Courantes

1. **"Expecting value: line 2 column 1"**: Rate limiting atteint, augmenter les délais
2. **"RuntimeError: Working outside of request context"**: Tokens non extraits avant threading
3. **"OperationalError: database is locked"**: Accès concurrent SQLite, utiliser WAL mode
4. **401 Unauthorized**: Tokens OAuth expirés ou invalides, réauthentifier

### Vérification Santé

```bash
# Test imports Python
python -c "import app; print('✓ Import successful')"

# Vérification base de données
python -c "from database import DatabaseManager; db = DatabaseManager(); print(db.get_cache_stats())"

# Test connexion Discogs (nécessite .env)
python -c "import discogs_client; print('✓ Client OK')"
```

## Contacts et Ressources

- **Documentation Discogs API**: https://www.discogs.com/developers
- **discogs-client Python**: https://github.com/joalla/discogs_client
- **Flask Documentation**: https://flask.palletsprojects.com/
- **SQLAlchemy ORM**: https://docs.sqlalchemy.org/

---

**Dernière mise à jour**: 7 janvier 2026
**Version du projet**: 1.0.0
**Python requis**: 3.13+
