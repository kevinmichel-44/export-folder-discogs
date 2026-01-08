# Import des dumps Discogs

Ce système importe automatiquement les dumps de données Discogs (artists, labels, masters, releases) dans la base de données locale.

## Types de dumps disponibles

Discogs fournit 4 types de dumps mensuels :

1. **artists** (~456 MB) - Informations sur les artistes
2. **labels** (~82 MB) - Informations sur les labels
3. **masters** (~567 MB) - Versions master des releases
4. **releases** (~10.3 GB) - Tous les releases

Total : **~11.4 GB compressés**, environ **15-17 millions d'enregistrements**

## Structure de la base de données

### Table `cached_artists`
- `id` - ID Discogs de l'artiste
- `name` - Nom de l'artiste
- `real_name` - Nom réel
- `profile` - Biographie
- `urls` - Sites web (CSV)
- `name_variations` - Variations du nom (CSV)
- `aliases` - Alias (CSV)

### Table `cached_labels`
- `id` - ID Discogs du label
- `name` - Nom du label
- `contact_info` - Contact
- `profile` - Description
- `urls` - Sites web (CSV)
- `parent_label` - Label parent
- `sublabels` - Sous-labels (CSV)

### Table `cached_masters`
- `id` - ID Discogs du master
- `title` - Titre
- `artists` - Artistes (CSV)
- `main_release` - Release principal
- `year` - Année
- `genres` - Genres (CSV)
- `styles` - Styles (CSV)

### Table `cached_releases`
- `id` - ID Discogs du release
- `title` - Titre
- `artists` - Artistes (CSV)
- `labels` - Labels (CSV)
- `catno` - Numéros de catalogue (CSV)
- `country` - Pays
- `year` - Année
- `genres` - Genres (CSV)
- `styles` - Styles (CSV)
- `url` - URL Discogs

## Installation

```bash
cd /home/kevin/Documents/project/export-folder-discogs
source venv/bin/activate
pip install requests  # Si pas déjà installé
```

## Utilisation

### Import complet de tous les dumps

```bash
python scripts/import_all_dumps.py
```

Cela télécharge et importe les 4 types de dumps (artists, labels, masters, releases).

**Temps estimé** : 3-6 heures selon la connexion et le processeur  
**Espace disque requis** : ~25-30 GB (dumps + database)

### Import sélectif

Importer uniquement certains types :

```bash
# Seulement artists et labels (rapide, ~500 MB)
python scripts/import_all_dumps.py --types artists labels

# Seulement releases (le plus gros)
python scripts/import_all_dumps.py --types releases
```

### Test avec limitation

Pour tester sans tout importer :

```bash
# Importer seulement 1000 entrées de chaque type
python scripts/import_all_dumps.py --limit 1000

# Test rapide avec artists et labels seulement
python scripts/import_all_dumps.py --types artists labels --limit 500
```

### Utiliser des dumps déjà téléchargés

```bash
# Ne pas re-télécharger les fichiers
python scripts/import_all_dumps.py --skip-download
```

Les dumps doivent être dans `data/dumps/` avec le format :
- `discogs_20260101_artists.xml.gz`
- `discogs_20260101_labels.xml.gz`
- `discogs_20260101_masters.xml.gz`
- `discogs_20260101_releases.xml.gz`

### Spécifier un mois précis

```bash
# Importer les dumps de janvier 2026
python scripts/import_all_dumps.py --year-month "2026/01"
```

## Configuration du cron

Pour importer automatiquement tous les dumps le 1er de chaque mois à 3h du matin :

```bash
crontab -e
```

Ajouter :

```bash
0 3 1 * * /home/kevin/Documents/project/export-folder-discogs/scripts/cron_import_all_dumps.sh
```

### Vérifier les logs

Les logs sont sauvegardés dans `logs/` :

```bash
# Voir le dernier log
ls -t logs/import_all_dumps_*.log | head -1 | xargs tail -f

# Voir tous les logs
ls -lh logs/import_all_dumps_*.log
```

Seuls les 10 derniers logs sont conservés (rotation automatique).

## Ordre d'import recommandé

Le script importe dans cet ordre optimal :

1. **artists** (le plus petit, ~456 MB)
2. **labels** (petit, ~82 MB)
3. **masters** (moyen, ~567 MB)
4. **releases** (le plus gros, ~10.3 GB)

Cela permet de détecter rapidement les problèmes avant l'import du gros fichier releases.

## Dédoublonnage

Le script vérifie automatiquement les entrées existantes :
- Enregistrements déjà présents → **skippés**
- Nouveaux enregistrements → **importés**

Aucun doublon ne sera créé en réexécutant le script.

## Exemples de sortie

### Import complet

```
============================================================
Discogs Data Dumps Import
============================================================
Types to import: artists, labels, masters, releases

============================================================
Processing ARTISTS
============================================================
[ARTISTS] Checking URL: https://discogs-data-dumps.s3.us-west-2.amazonaws.com/data/2026/01/discogs_20260101_artists.xml.gz
[ARTISTS] Found dump: discogs_20260101_artists.xml.gz (455.8 MB)
[DOWNLOAD] Downloading discogs_20260101_artists.xml.gz...
[DOWNLOAD] Progress: 100.0% (455.8 MB)
[ARTISTS] Parsing data/dumps/discogs_20260101_artists.xml.gz...
[ARTISTS] Imported: 8,234,567 (skipped: 0)
[ARTISTS] ✓ Import complete: 8,234,567 artists imported, 0 skipped

============================================================
Processing LABELS
============================================================
[LABELS] Imported: 1,456,789 (skipped: 0)
[LABELS] ✓ Import complete: 1,456,789 labels imported, 0 skipped

============================================================
Processing MASTERS
============================================================
[MASTERS] Imported: 2,345,678 (skipped: 0)
[MASTERS] ✓ Import complete: 2,345,678 masters imported, 0 skipped

============================================================
Processing RELEASES
============================================================
[RELEASES] Imported: 16,789,123 (skipped: 0)
[RELEASES] ✓ Import complete: 16,789,123 releases imported, 0 skipped

============================================================
✓ Import complete!
Total records imported: 28,826,157
============================================================
```

### Import avec limitation (test)

```
Types to import: artists, labels, masters, releases
Limit per dump: 1,000 records

[ARTISTS] Imported: 1,000 (skipped: 0)
[ARTISTS] ✓ Import complete: 1,000 artists imported, 0 skipped

[LABELS] Imported: 1,000 (skipped: 0)
[LABELS] ✓ Import complete: 1,000 labels imported, 0 skipped

[MASTERS] Imported: 1,000 (skipped: 0)
[MASTERS] ✓ Import complete: 1,000 masters imported, 0 skipped

[RELEASES] Imported: 1,000 (skipped: 0)
[RELEASES] ✓ Import complete: 1,000 releases imported, 0 skipped

✓ Import complete!
Total records imported: 4,000
```

## Optimisations futures possibles

1. **Compression de la base de données**
   ```bash
   sqlite3 discogs_cache.db "VACUUM;"
   ```

2. **Index pour recherches rapides**
   ```sql
   CREATE INDEX idx_artist_name ON cached_artists(name);
   CREATE INDEX idx_label_name ON cached_labels(name);
   CREATE INDEX idx_release_title ON cached_releases(title);
   CREATE INDEX idx_release_year ON cached_releases(year);
   ```

3. **Import parallèle** (avec précaution)
   - Les 4 dumps pourraient être importés en parallèle
   - Nécessite plus de RAM et CPU
   - Risque de lock SQLite

## Dépannage

### Erreur de téléchargement

```
[ARTISTS] Error checking URL: Connection timeout
```

→ Vérifier la connexion internet ou réessayer plus tard

### Erreur d'espace disque

```
[RELEASES] Error: No space left on device
```

→ Libérer de l'espace (au moins 30 GB recommandés)

### Imports dupliqués

Le script évite automatiquement les doublons. Si vous voulez réimporter :

```bash
# Supprimer la base de données
rm discogs_cache.db

# Réimporter
python scripts/import_all_dumps.py
```

## URLs des dumps

- **Index S3** : https://discogs-data-dumps.s3.us-west-2.amazonaws.com/index.html
- **Dossier courant** : https://discogs-data-dumps.s3.us-west-2.amazonaws.com/index.html?prefix=data/2026/
- **Documentation Discogs** : https://data.discogs.com/

## Avantages de cette approche

✅ **Pas de rate limiting** - Données locales, pas d'appels API  
✅ **Recherche rapide** - Index SQLite optimisés  
✅ **Offline** - Fonctionne sans connexion après import  
✅ **Complet** - 15+ millions de releases disponibles  
✅ **Automatique** - Mise à jour mensuelle via cron  
✅ **Déduplication** - Évite les doublons automatiquement
