from flask import Flask, render_template, request, session, redirect, url_for, send_file
import discogs_client
import csv
import re
import io
import os
from datetime import timedelta
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
app.permanent_session_lifetime = timedelta(hours=2)

# Configuration OAuth Discogs
# Obtenez vos clés sur https://www.discogs.com/settings/developers
CONSUMER_KEY = os.environ.get('DISCOGS_CONSUMER_KEY', '')
CONSUMER_SECRET = os.environ.get('DISCOGS_CONSUMER_SECRET', '')
CALLBACK_URL = os.environ.get('CALLBACK_URL', 'http://127.0.0.1:5000/callback')


@app.route('/')
def index():
    """Page d'accueil avec bouton de connexion OAuth"""
    if 'access_token' in session and 'access_secret' in session:
        return redirect(url_for('folders'))
    return render_template('login.html')


@app.route('/login')
def login():
    """Initiation du processus OAuth"""
    if not CONSUMER_KEY or not CONSUMER_SECRET:
        return render_template('login.html', 
                             error="Configuration OAuth manquante. Veuillez configurer DISCOGS_CONSUMER_KEY et DISCOGS_CONSUMER_SECRET.")
    
    try:
        d = discogs_client.Client('DiscogsExportApp/1.0')
        d.set_consumer_key(CONSUMER_KEY, CONSUMER_SECRET)
        
        # Obtenir le token de demande et l'URL d'autorisation
        token, secret, url = d.get_authorize_url(callback_url=CALLBACK_URL)
        
        # Stocker les tokens temporaires en session
        session['request_token'] = token
        session['request_secret'] = secret
        
        return redirect(url)
    except Exception as e:
        return render_template('login.html', 
                             error=f"Erreur lors de l'initialisation OAuth: {str(e)}")


@app.route('/callback')
def callback():
    """Callback OAuth après autorisation de l'utilisateur"""
    if 'request_token' not in session or 'request_secret' not in session:
        return render_template('login.html', 
                             error="Session expirée. Veuillez recommencer la connexion.")
    
    oauth_verifier = request.args.get('oauth_verifier')
    if not oauth_verifier:
        return render_template('login.html', 
                             error="Autorisation refusée ou code de vérification manquant.")
    
    try:
        # Récupérer les tokens de requête de la session
        request_token = session['request_token']
        request_secret = session['request_secret']
        
        d = discogs_client.Client('DiscogsExportApp/1.0')
        d.set_consumer_key(CONSUMER_KEY, CONSUMER_SECRET)
        
        # Définir les tokens de requête avant d'échanger
        d.set_token(request_token, request_secret)
        
        # Échanger le verifier contre les tokens d'accès
        access_token, access_secret = d.get_access_token(oauth_verifier)
        
        # Stocker les tokens d'accès en session
        session.permanent = True
        session['access_token'] = access_token
        session['access_secret'] = access_secret
        
        # Nettoyer les tokens temporaires
        session.pop('request_token', None)
        session.pop('request_secret', None)
        
        # Obtenir le nom d'utilisateur
        d.set_token(access_token, access_secret)
        me = d.identity()
        session['username'] = me.username
        
        return redirect(url_for('folders'))
    except Exception as e:
        # Nettoyer la session en cas d'erreur
        session.pop('request_token', None)
        session.pop('request_secret', None)
        return render_template('login.html', 
                             error=f"Erreur lors de l'authentification: {str(e)}")


@app.route('/folders')
def folders():
    """Affichage des dossiers de l'utilisateur"""
    if 'access_token' not in session or 'access_secret' not in session:
        return redirect(url_for('index'))
    
    try:
        d = discogs_client.Client('DiscogsExportApp/1.0')
        d.set_consumer_key(CONSUMER_KEY, CONSUMER_SECRET)
        d.set_token(session['access_token'], session['access_secret'])
        me = d.identity()
        
        # Récupérer tous les dossiers
        folders_list = []
        collection_folders = me.collection_folders
        for folder in collection_folders:
            folders_list.append({
                'id': folder.id,
                'name': folder.name,
                'count': folder.count
            })
        
        return render_template('folders.html', 
                             username=session.get('username', 'Utilisateur'),
                             folders=folders_list)
    except Exception as e:
        session.clear()
        return redirect(url_for('index'))


@app.route('/export/<int:folder_id>')
def export_folder(folder_id):
    """Export d'un dossier en CSV"""
    if 'access_token' not in session or 'access_secret' not in session:
        return redirect(url_for('index'))
    
    try:
        d = discogs_client.Client('DiscogsExportApp/1.0')
        d.set_consumer_key(CONSUMER_KEY, CONSUMER_SECRET)
        d.set_token(session['access_token'], session['access_secret'])
        me = d.identity()
        
        # Trouver le dossier correspondant
        folder_name = "Unknown"
        releases = []
        
        collection_folders = me.collection_folders
        for folder in collection_folders:
            if folder.id == folder_id:
                folder_name = folder.name
                
                # Récupérer toutes les releases du dossier
                for collection_item in folder.releases:
                    release_id = collection_item.id
                    release = d.release(release_id)
                    
                    # Extraire les artistes
                    artists = []
                    for artist in release.artists:
                        artist_filtered_name = re.sub(r'\(.*\)', '', artist.name)
                        artists.append(artist_filtered_name)
                    
                    # Extraire les labels et numéros de catalogue
                    labels = []
                    catnos = []
                    if hasattr(release, 'labels') and release.labels:
                        for label in release.labels:
                            # Accéder aux données via data si c'est un objet APIObject
                            if hasattr(label, 'data'):
                                label_name = label.data.get('name', 'Unknown')
                                label_catno = label.data.get('catno', '')
                            else:
                                label_name = getattr(label, 'name', 'Unknown')
                                label_catno = getattr(label, 'catno', '')
                            
                            label_filtered_name = re.sub(r'\(.*\)', '', label_name)
                            labels.append(label_filtered_name)
                            catnos.append(label_catno if label_catno else 'N/A')
                    
                    artists_str = ' - '.join(artists) if artists else 'Unknown Artist'
                    labels_str = ' - '.join(labels) if labels else 'Unknown Label'
                    catnos_str = ' , '.join(catnos) if catnos else 'N/A'
                    genres = ' , '.join(release.genres) if hasattr(release, 'genres') and release.genres else ''
                    styles = ' , '.join(release.styles) if hasattr(release, 'styles') and release.styles else ''
                    
                    # Prix du marché - accéder via data
                    price = "N/A"
                    try:
                        if hasattr(release, 'data') and 'lowest_price' in release.data:
                            price_val = release.data.get('lowest_price')
                            if price_val:
                                price = f"{price_val}"
                        elif hasattr(release, 'lowest_price') and release.lowest_price:
                            price = str(release.lowest_price)
                    except Exception:
                        price = "N/A"
                    
                    releases.append({
                        'title': release.title if hasattr(release, 'title') else 'Unknown',
                        'artists': artists_str,
                        'labels': labels_str,
                        'catno': catnos_str,
                        'country': release.country if hasattr(release, 'country') else '',
                        'year': release.year if hasattr(release, 'year') else '',
                        'genres': genres,
                        'styles': styles,
                        'price': price,
                        'url': release.url if hasattr(release, 'url') else ''
                    })
                    
                    # Log pour debug
                    print(f"Exported: {artists_str} - {release.title} | Price: {price}")
                break
        
        # Créer le fichier CSV en mémoire
        output = io.StringIO()
        csv_columns = ['title', 'artists', 'labels', 'catno', 'country', 'year', 'genres', 'styles', 'price', 'url']
        writer = csv.DictWriter(output, fieldnames=csv_columns)
        writer.writeheader()
        for data in releases:
            writer.writerow(data)
        
        # Convertir en bytes pour l'envoi
        output.seek(0)
        bytes_output = io.BytesIO(output.getvalue().encode('utf-8'))
        bytes_output.seek(0)
        
        # Générer un nom de fichier sécurisé
        safe_filename = re.sub(r'[^\w\s-]', '', folder_name).strip().replace(' ', '_')
        
        return send_file(
            bytes_output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'{safe_filename}_export.csv'
        )
        
    except Exception as e:
        return f"Erreur lors de l'export: {str(e)}", 500


@app.route('/logout')
def logout():
    """Déconnexion"""
    session.clear()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
