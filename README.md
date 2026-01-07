# export-folder-discogs

Export discogs releases from a specific folder in CSV

## 🎵 Interface Web

Une interface web Flask simple et élégante pour exporter vos dossiers Discogs en CSV avec authentification OAuth sécurisée.

### Fonctionnalités

- ✅ Connexion OAuth sécurisée avec Discogs
- ✅ Affichage de tous vos dossiers personnels
- ✅ Export en CSV d'un dossier en un clic
- ✅ Interface moderne et responsive
- ✅ Sessions persistantes (2 heures)

### Configuration OAuth

#### 1. Créer une application Discogs

1. Connectez-vous sur [Discogs](https://www.discogs.com)
2. Allez dans **Settings → Developers** : https://www.discogs.com/settings/developers
3. Cliquez sur **Create an App** (ou **Create New Application**)
4. Remplissez les informations :
   - **Name** : `Discogs Export Tool` (ou le nom de votre choix)
   - **Description** : `Application web pour exporter mes collections Discogs`
   - **Website** : `http://127.0.0.1:5000`
   - **Callback URL** : `http://127.0.0.1:5000/callback`
5. Sauvegardez et notez votre **Consumer Key** et **Consumer Secret**

#### 2. Configurer l'application

1. Copiez le fichier d'exemple :
```bash
cp .env.example .env
```

2. Éditez le fichier `.env` et ajoutez vos clés :
```bash
DISCOGS_CONSUMER_KEY=votre_consumer_key_ici
DISCOGS_CONSUMER_SECRET=votre_consumer_secret_ici
CALLBACK_URL=http://127.0.0.1:5000/callback
SECRET_KEY=une_cle_secrete_aleatoire
```

⚠️ **Important** : Ne partagez jamais votre fichier `.env` (il est déjà dans `.gitignore`)

### Installation

1. Créer un environnement virtuel :
```bash
python3 -m venv venv
source venv/bin/activate  # Sur Windows: venv\Scripts\activate
```

2. Installer les dépendances :
```bash
pip install -r requirements.txt
```

3. Lancer l'application :
```bash
python app.py
```

4. Ouvrir votre navigateur sur `http://localhost:5000`

### Utilisation

1. **Connexion** : Cliquez sur "Se connecter avec Discogs"
   - Vous serez redirigé vers Discogs pour autoriser l'application
   - Autorisez l'accès à votre collection
   
2. **Voir vos dossiers** : Une fois connecté, vous verrez tous vos dossiers avec le nombre de releases

3. **Télécharger** : Cliquez sur "Télécharger CSV" pour exporter un dossier

### Format CSV

Le fichier CSV exporté contient les colonnes suivantes :
- **Title** - Titre de la release
- **Artists** - Artistes
- **Labels** - Labels
- **Catno** - Numéro de catalogue
- **Country** - Pays
- **Year** - Année
- **Genres** - Genres musicaux
- **Styles** - Styles
- **Price** - Prix le plus bas sur le marché
- **URL** - Lien Discogs

### Déploiement en production

Pour un déploiement en production, modifiez dans votre `.env` :
```bash
CALLBACK_URL=https://votre-domaine.com/callback
```

Et mettez à jour l'URL de callback dans les paramètres de votre application Discogs.

### Sécurité

- Les tokens OAuth sont stockés en session (durée : 2 heures)
- Le fichier `.env` est exclu du versioning Git
- Utilisez HTTPS en production pour protéger les tokens

## 🐳 Déploiement Docker

### Image Docker

L'application est disponible en image Docker via GitHub Container Registry.

#### Build local de l'image

```bash
docker build -t discogs-export .
```

#### Utiliser l'image depuis GitHub Packages

```bash
docker pull ghcr.io/kevinmichel-44/export-folder-discogs:latest
```

### Déploiement avec Docker Compose

1. **Créer un fichier `.env`** (copier depuis `.env.docker`) :
```bash
cp .env.docker .env
```

2. **Éditer `.env`** avec vos clés OAuth Discogs :
```env
DISCOGS_CONSUMER_KEY=votre_consumer_key
DISCOGS_CONSUMER_SECRET=votre_consumer_secret
CALLBACK_URL=https://votre-domaine.com/callback
SECRET_KEY=une_cle_secrete_aleatoire_longue
```

3. **Lancer avec Docker Compose** :
```bash
docker-compose up -d
```

4. **Accéder à l'application** :
- Local : `http://localhost:5000`
- Production : `https://votre-domaine.com`

### Configuration pour production

Pour un déploiement en production avec reverse proxy (Traefik, Nginx, etc.) :

1. Modifier le `CALLBACK_URL` dans `.env` :
```env
CALLBACK_URL=https://votre-domaine.com/callback
```

2. Mettre à jour l'URL de callback dans les paramètres de votre application Discogs

3. Le docker-compose inclut des labels Traefik (commentez si vous n'utilisez pas Traefik)

### CI/CD

L'image Docker est automatiquement buildée et publiée sur GitHub Container Registry via GitHub Actions à chaque push sur `main`/`master` ou lors de la création d'un tag.

**Tags disponibles :**
- `latest` : dernière version de la branche principale
- `main` ou `master` : version de la branche correspondante
- `v1.0.0` : versions taguées (si vous créez des releases)

### Variables d'environnement Docker

| Variable | Description | Requis | Défaut |
|----------|-------------|--------|---------|
| `DISCOGS_CONSUMER_KEY` | Consumer Key de votre app Discogs | ✅ Oui | - |
| `DISCOGS_CONSUMER_SECRET` | Consumer Secret de votre app Discogs | ✅ Oui | - |
| `CALLBACK_URL` | URL de callback OAuth | Non | `http://localhost:5000/callback` |
| `SECRET_KEY` | Clé secrète Flask pour les sessions | ⚠️ Recommandé | Généré aléatoirement |

### Logs et monitoring

Voir les logs du conteneur :
```bash
docker-compose logs -f discogs-export
```

Redémarrer le conteneur :
```bash
docker-compose restart discogs-export
```

Arrêter et supprimer :
```bash
docker-compose down
```

## 📝 Script en ligne de commande

Le script original `get_folder.py` reste disponible pour une utilisation en ligne de commande.
