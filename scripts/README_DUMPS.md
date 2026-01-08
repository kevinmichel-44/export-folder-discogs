# Discogs Data Dump Importer

Système d'import automatique des dumps mensuels Discogs pour alimenter la base de données locale.

## Installation

1. **Installer les dépendances** (si nécessaire):
```bash
pip install requests
```

2. **Configurer le cron** (le 1er de chaque mois à 3h du matin):
```bash
crontab -e
```

Ajouter cette ligne:
```
0 3 1 * * /home/kevin/Documents/project/export-folder-discogs/scripts/cron_import_dump.sh
```

## Usage Manuel

### Import simple
```bash
cd /home/kevin/Documents/project/export-folder-discogs
source venv/bin/activate
python scripts/import_discogs_dump.py
```

### Test avec limite
```bash
python scripts/import_discogs_dump.py --limit 1000
```

### Utiliser un dump déjà téléchargé
```bash
python scripts/import_discogs_dump.py --skip-download
```

## Fonctionnement

1. **Téléchargement**: Le script trouve et télécharge automatiquement le dump le plus récent depuis AWS S3
2. **Parsing**: Parse le fichier XML.gz (plusieurs GB) de manière efficiente
3. **Import**: Insère les releases dans `discogs_cache.db`
4. **Déduplication**: Skip les releases déjà présentes en base

## Avantages

- ✅ **Offline**: Toutes les données Discogs disponibles localement
- ✅ **Performance**: Pas de rate limiting, lectures ultra-rapides
- ✅ **Économie**: Réduit drastiquement les appels API
- ✅ **Automatique**: Mise à jour mensuelle via cron

## Taille des données

- **Releases dump**: ~4-5 GB compressé, ~15-20 GB décompressé
- **Base de données finale**: ~10-15 GB (selon optimisations SQLite)
- **Nombre de releases**: ~15-17 millions

## Logs

Les logs sont sauvegardés dans `logs/import_dump_YYYYMMDD_HHMMSS.log`

Seuls les 10 derniers logs sont conservés.

## Exemple d'output

```
======================================================================
  DISCOGS DATA DUMP IMPORTER
======================================================================

Checking https://discogs-data-dumps.s3.us-west-2.amazonaws.com/data/2026/discogs_20260101_releases.xml.gz...
✓ Found: discogs_20260101_releases.xml.gz (4523.2 MB)

Downloading discogs_20260101_releases.xml.gz...
Progress: 100.0% (4523.2 MB)
✓ Downloaded: data/dumps/discogs_20260101_releases.xml.gz

Parsing releases from data/dumps/discogs_20260101_releases.xml.gz...
Processed 10,000 releases (imported: 9,847, skipped: 153)
Processed 20,000 releases (imported: 19,534, skipped: 466)
...

✓ Import complete!
  Total processed: 15,234,567
  Imported: 15,234,102
  Skipped (already in DB): 465
```

## Optimisations futures

- [ ] Import parallèle par chunks
- [ ] Compression des données texte
- [ ] Index supplémentaires pour recherche
- [ ] Support artists, labels, masters dumps
- [ ] Delta updates (incremental)
