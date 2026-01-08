from flask import Flask, render_template, request, session, redirect, url_for, send_file, Response, stream_with_context
import discogs_client
import csv
import re
import io
import os
import logging
import json
import time
from datetime import timedelta
from dotenv import load_dotenv
from database import DatabaseManager

# Charger les variables d'environnement
load_dotenv()

# Configurer les logs pour ignorer les erreurs SSL en dev
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

# IMPORTANT: Si SECRET_KEY n'est pas définie dans .env, elle sera générée aléatoirement
# ce qui invalide les sessions à chaque redémarrage du serveur
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    print("[APP] WARNING: SECRET_KEY not set in .env, generating random key (sessions will be lost on restart)")
    secret_key = os.urandom(24).hex()
else:
    print("[APP] SECRET_KEY loaded from .env")

app.secret_key = secret_key
app.permanent_session_lifetime = timedelta(hours=2)

# Configuration OAuth Discogs
# Obtenez vos clés sur https://www.discogs.com/settings/developers
CONSUMER_KEY = os.environ.get('DISCOGS_CONSUMER_KEY', '')
CONSUMER_SECRET = os.environ.get('DISCOGS_CONSUMER_SECRET', '')
CALLBACK_URL = os.environ.get('CALLBACK_URL', 'http://127.0.0.1:5000/callback')

# Stockage temporaire pour la progression
export_progress = {}

# Initialize database manager
db_manager = None
try:
    db_manager = DatabaseManager()
    db_manager.init_db()
    print("[APP] Database cache initialized successfully")
except Exception as e:
    print(f"[APP] Warning: Could not initialize database cache: {str(e)}")
    print("[APP] App will continue without caching")
    db_manager = None


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
    print(f"[OAUTH] Callback reçu avec params: {request.args}")
    print(f"[OAUTH] Session keys: {list(session.keys())}")
    
    if 'request_token' not in session or 'request_secret' not in session:
        print("[OAUTH] ERROR: Tokens de requête manquants en session")
        return render_template('login.html', 
                             error="Session expirée. Veuillez recommencer la connexion.")
    
    oauth_verifier = request.args.get('oauth_verifier')
    if not oauth_verifier:
        print("[OAUTH] ERROR: oauth_verifier manquant")
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
        print(f"[OAUTH] Échange du verifier...")
        access_token, access_secret = d.get_access_token(oauth_verifier)
        print(f"[OAUTH] Tokens d'accès obtenus")
        
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
        print(f"[OAUTH] Authentification réussie pour {me.username}")
        
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
    print(f"[FOLDERS] Route accessed, session keys: {list(session.keys())}")
    
    if 'access_token' not in session or 'access_secret' not in session:
        print("[FOLDERS] ERROR: Tokens not in session, redirecting to index")
        return redirect(url_for('index'))
    
    try:
        print(f"[FOLDERS] Creating Discogs client with tokens from session")
        d = discogs_client.Client('DiscogsExportApp/1.0')
        d.set_consumer_key(CONSUMER_KEY, CONSUMER_SECRET)
        d.set_token(session['access_token'], session['access_secret'])
        
        print(f"[FOLDERS] Getting user identity...")
        me = d.identity()
        print(f"[FOLDERS] User: {me.username}")
        
        # Récupérer tous les dossiers
        folders_list = []
        collection_folders = me.collection_folders
        print(f"[FOLDERS] Fetching folders...")
        for folder in collection_folders:
            folders_list.append({
                'id': folder.id,
                'name': folder.name,
                'count': folder.count
            })
        
        print(f"[FOLDERS] Found {len(folders_list)} folders")
        
        # Get cache statistics
        cache_stats = {'total_cached': 0, 'cached_last_week': 0}
        if db_manager:
            cache_stats = db_manager.get_cache_stats()
        
        print(f"[FOLDERS] Rendering template with username={session.get('username', 'Utilisateur')}")
        return render_template('folders.html', 
                             username=session.get('username', 'Utilisateur'),
                             folders=folders_list,
                             cache_stats=cache_stats)
    except Exception as e:
        print(f"[FOLDERS] ERROR: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        session.clear()
        return redirect(url_for('index'))


@app.route('/marketplace')
def marketplace():
    """Display user's marketplace inventory"""
    if 'access_token' not in session or 'access_secret' not in session:
        return redirect(url_for('index'))
    
    try:
        d = discogs_client.Client('DiscogsExportApp/1.0')
        d.set_consumer_key(CONSUMER_KEY, CONSUMER_SECRET)
        d.set_token(session['access_token'], session['access_secret'])
        me = d.identity()
        
        # Get marketplace inventory count
        total_items = 0
        try:
            inventory = list(me.inventory)
            # Filter only items for sale (not sold)
            for_sale_items = [item for item in inventory if hasattr(item, 'status') and item.status == 'For Sale']
            total_items = len(for_sale_items)
            print(f"Found {total_items} items for sale (out of {len(inventory)} total listings)")
        except Exception as e:
            print(f"Error counting inventory: {str(e)}")
            total_items = 0
        
        return render_template('marketplace.html', 
                             username=session.get('username', 'User'),
                             total_items=total_items)
    except Exception as e:
        print(f"Marketplace error: {str(e)}")
        session.clear()
        return redirect(url_for('index'))


@app.route('/export/<int:folder_id>')
def export_folder(folder_id):
    """Export d'un dossier en CSV"""
    if 'access_token' not in session or 'access_secret' not in session:
        return redirect(url_for('index'))
    
    # Initialiser la progression
    export_id = f"{session.get('username', 'user')}_{folder_id}_{int(time.time())}"
    export_progress[export_id] = {
        'current': 0,
        'total': 0,
        'status': 'starting',
        'folder_name': ''
    }
    
    try:
        print(f"[COLLECTION] Starting export with ID: {export_id}")
        d = discogs_client.Client('DiscogsExportApp/1.0')
        d.set_consumer_key(CONSUMER_KEY, CONSUMER_SECRET)
        d.set_token(session['access_token'], session['access_secret'])
        me = d.identity()
        
        print(f"[COLLECTION] Getting collection folders for user: {me.username}")
        
        # Trouver le dossier correspondant
        folder_name = "Unknown"
        releases = []
        
        collection_folders = me.collection_folders
        for folder in collection_folders:
            if folder.id == folder_id:
                folder_name = folder.name
                total_releases = folder.count
                
                print(f"[COLLECTION] Found folder '{folder_name}' with {total_releases} releases")
                
                # Mettre à jour la progression
                export_progress[export_id]['total'] = total_releases
                export_progress[export_id]['folder_name'] = folder_name
                export_progress[export_id]['status'] = 'processing'
                
                # Récupérer toutes les releases du dossier
                cache_hits = 0
                api_calls = 0
                
                for idx, collection_item in enumerate(folder.releases, 1):
                    # Mettre à jour la progression
                    export_progress[export_id]['current'] = idx
                    
                    # Log progress every 25 items
                    if idx % 25 == 0 or idx == 1:
                        print(f"[COLLECTION] Processing release {idx}/{total_releases} (cache hits: {cache_hits}, API calls: {api_calls})")
                    
                    release_id = collection_item.id
                    release_data = None
                    
                    # Try to get from cache first
                    if db_manager:
                        cached_data = db_manager.get_cached_release(release_id)
                        if cached_data:
                            release_data = cached_data
                            cache_hits += 1
                            # Skip rate limiting for cached items
                        else:
                            # Not in cache, will need to fetch from API
                            # Rate limiting - Discogs allows 60 requests per minute for authenticated requests
                            # = 1 request per second. We use 1.1s to be safe
                            if api_calls > 0:
                                time.sleep(1.1)
                    else:
                        # No cache available, always apply rate limiting
                        if idx > 1:
                            time.sleep(1.1)
                    
                    # If not in cache, fetch from API
                    if release_data is None:
                        # Retry logic for rate limiting
                        max_retries = 3
                        retry_delay = 5
                        
                        for retry in range(max_retries):
                            try:
                                release = d.release(release_id)
                                api_calls += 1
                                break  # Success, exit retry loop
                            except Exception as rate_error:
                                error_msg = str(rate_error)
                                # Check if it's a rate limit error
                                if 'Expecting value' in error_msg or '429' in error_msg:
                                    if retry < max_retries - 1:
                                        wait_time = retry_delay * (retry + 1)
                                        print(f"[COLLECTION] Rate limit hit at release {idx}, waiting {wait_time}s (retry {retry + 1}/{max_retries})...")
                                        time.sleep(wait_time)
                                        continue
                                    else:
                                        print(f"[COLLECTION] Failed after {max_retries} retries for release {idx}: {error_msg}")
                                        raise
                                else:
                                    # Different error, don't retry
                                    raise
                        
                        try:
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
                            
                            release_data = {
                                'title': release.title if hasattr(release, 'title') else 'Unknown',
                                'artists': artists_str,
                                'labels': labels_str,
                                'catno': catnos_str,
                                'country': release.country if hasattr(release, 'country') else '',
                                'year': str(release.year) if hasattr(release, 'year') else '',
                                'genres': genres,
                                'styles': styles,
                                'price': price,
                                'url': release.url if hasattr(release, 'url') else ''
                            }
                            
                            # Cache the release data for future use
                            if db_manager:
                                db_manager.cache_release(release_id, release_data)
                            
                        except Exception as rel_error:
                            print(f"[COLLECTION] Error processing release {idx}: {str(rel_error)}")
                            # Skip problematic releases
                            continue
                    
                    # Add to releases list
                    if release_data:
                        releases.append(release_data)
                
                # Marquer comme terminé
                export_progress[export_id]['status'] = 'completed'
                print(f"[COLLECTION] Export completed with {len(releases)} releases")
                print(f"[COLLECTION] Cache hits: {cache_hits}, API calls: {api_calls}, Cache efficiency: {cache_hits/(cache_hits+api_calls)*100:.1f}%" if (cache_hits + api_calls) > 0 else "[COLLECTION] No data processed")
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
        
        # Nettoyer la progression après un délai
        def cleanup():
            time.sleep(5)
            export_progress.pop(export_id, None)
        
        import threading
        threading.Thread(target=cleanup).start()
        
        return send_file(
            bytes_output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'{safe_filename}_export.csv'
        )
        
    except Exception as e:
        print(f"[COLLECTION] Critical error: {str(e)}")
        import traceback
        traceback.print_exc()
        export_progress[export_id]['status'] = 'error'
        export_progress[export_id]['error'] = str(e)
        return f"Erreur lors de l'export: {str(e)}", 500


@app.route('/progress/<int:folder_id>')
def progress(folder_id):
    """Stream SSE pour la progression de l'export"""
    def generate():
        username = session.get('username', 'user')
        
        # Attendre que l'export démarre (max 10 secondes)
        export_id = None
        for _ in range(20):  # 20 * 0.5s = 10 secondes max
            # Chercher l'export le plus récent pour ce dossier
            for eid in list(export_progress.keys()):
                if eid.startswith(f"{username}_{folder_id}_"):
                    export_id = eid
                    break
            
            if export_id:
                break
            
            time.sleep(0.5)
            yield f"data: {json.dumps({'status': 'waiting', 'message': 'En attente...'})}\n\n"
        
        if not export_id:
            yield f"data: {json.dumps({'status': 'error', 'message': 'Export non trouvé'})}\n\n"
            return
        
        # Streamer la progression
        last_status = None
        while True:
            if export_id not in export_progress:
                # L'export a été nettoyé, il est terminé
                if last_status == 'completed':
                    break
                yield f"data: {json.dumps({'status': 'completed', 'current': 0, 'total': 0, 'percent': 100})}\n\n"
                break
            
            progress_data = export_progress[export_id]
            last_status = progress_data['status']
            
            # Calculer le temps estimé (environ 1.5 secondes par release)
            if progress_data['total'] > 0 and progress_data['current'] > 0:
                progress_percent = (progress_data['current'] / progress_data['total']) * 100
                remaining = progress_data['total'] - progress_data['current']
                estimated_time = int(remaining * 1.5)  # 1.5 secondes par release
            else:
                progress_percent = 0
                estimated_time = int(progress_data.get('total', 0) * 1.5) if progress_data.get('total', 0) > 0 else 0
            
            data = {
                'status': progress_data['status'],
                'current': progress_data['current'],
                'total': progress_data['total'],
                'percent': round(progress_percent, 1),
                'estimated_time': estimated_time,
                'folder_name': progress_data['folder_name']
            }
            
            yield f"data: {json.dumps(data)}\n\n"
            
            if progress_data['status'] in ['completed', 'error']:
                break
            
            time.sleep(0.5)
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/export_marketplace')
def export_marketplace():
    """Export marketplace inventory to CSV"""
    if 'access_token' not in session or 'access_secret' not in session:
        return redirect(url_for('index'))
    
    # Initialize progress
    export_id = f"{session.get('username', 'user')}_marketplace_{int(time.time())}"
    export_progress[export_id] = {
        'current': 0,
        'total': 0,
        'status': 'starting',
        'folder_name': 'Marketplace'
    }
    
    try:
        print(f"[MARKETPLACE] Starting export with ID: {export_id}")
        d = discogs_client.Client('DiscogsExportApp/1.0')
        d.set_consumer_key(CONSUMER_KEY, CONSUMER_SECRET)
        d.set_token(session['access_token'], session['access_secret'])
        me = d.identity()
        
        print(f"[MARKETPLACE] Getting inventory for user: {me.username}")
        
        # Get inventory - Convert to list first
        try:
            all_items = list(me.inventory)
            # Filter only items for sale (not sold)
            for_sale_items = [item for item in all_items if hasattr(item, 'status') and item.status == 'For Sale']
            total_items = len(for_sale_items)
            print(f"[MARKETPLACE] Found {total_items} items for sale (out of {len(all_items)} total listings)")
        except Exception as inv_error:
            print(f"[MARKETPLACE] Error getting inventory: {str(inv_error)}")
            export_progress[export_id]['status'] = 'error'
            export_progress[export_id]['error'] = f"Cannot access inventory: {str(inv_error)}"
            return f"Error: {str(inv_error)}", 500
        
        listings = []
        
        if total_items == 0:
            print("[MARKETPLACE] No items for sale in inventory")
            export_progress[export_id]['status'] = 'completed'
            export_progress[export_id]['total'] = 0
        else:
            export_progress[export_id]['total'] = total_items
            export_progress[export_id]['status'] = 'processing'
            
            # Process each listing
            for idx, listing in enumerate(for_sale_items, 1):
                export_progress[export_id]['current'] = idx
                
                # Rate limiting - add delay every 50 items to avoid 429 errors
                if idx > 1 and idx % 50 == 0:
                    print(f"[MARKETPLACE] Rate limit pause at item {idx}...")
                    time.sleep(2)
                
                # Log progress every 25 items
                if idx % 25 == 0 or idx == 1:
                    print(f"[MARKETPLACE] Processing item {idx}/{total_items}")
                
                try:
                    # Get release info first
                    try:
                        release = listing.release
                    except Exception as rel_error:
                        print(f"[MARKETPLACE] Error getting release: {str(rel_error)}")
                        continue
                    
                    # Extract artists
                    artists = []
                    try:
                        if hasattr(release, 'artists') and release.artists:
                            for artist in release.artists:
                                artist_filtered_name = re.sub(r'\(.*\)', '', artist.name)
                                artists.append(artist_filtered_name)
                    except Exception:
                        pass
                    
                    # Extract labels and catalog numbers
                    labels = []
                    catnos = []
                    try:
                        if hasattr(release, 'labels') and release.labels:
                            for label in release.labels:
                                if hasattr(label, 'data'):
                                    label_name = label.data.get('name', 'Unknown')
                                    label_catno = label.data.get('catno', '')
                                else:
                                    label_name = getattr(label, 'name', 'Unknown')
                                    label_catno = getattr(label, 'catno', '')
                                
                                label_filtered_name = re.sub(r'\(.*\)', '', label_name)
                                labels.append(label_filtered_name)
                                catnos.append(label_catno if label_catno else 'N/A')
                    except Exception:
                        pass
                    
                    artists_str = ' - '.join(artists) if artists else 'Unknown Artist'
                    labels_str = ' - '.join(labels) if labels else 'Unknown Label'
                    catnos_str = ' , '.join(catnos) if catnos else 'N/A'
                    
                    try:
                        genres = ' , '.join(release.genres) if hasattr(release, 'genres') and release.genres else ''
                        styles = ' , '.join(release.styles) if hasattr(release, 'styles') and release.styles else ''
                    except Exception:
                        genres = ''
                        styles = ''
                    
                    # Listing details - extract each field individually
                    listing_price = 'N/A'
                    try:
                        if hasattr(listing, 'price') and listing.price:
                            listing_price = f"{listing.price.value} {listing.price.currency}"
                    except Exception:
                        pass
                    
                    condition = 'N/A'
                    try:
                        condition = listing.condition if hasattr(listing, 'condition') else 'N/A'
                    except Exception:
                        pass
                    
                    sleeve_condition = 'N/A'
                    try:
                        sleeve_condition = listing.sleeve_condition if hasattr(listing, 'sleeve_condition') else 'N/A'
                    except Exception:
                        pass
                    
                    comments = ''
                    try:
                        comments = listing.comments if hasattr(listing, 'comments') else ''
                    except Exception:
                        pass
                    
                    posted = ''
                    try:
                        if hasattr(listing, 'posted'):
                            # Access the raw data to avoid datetime parsing issues
                            if hasattr(listing, 'data') and 'posted' in listing.data:
                                posted = listing.data['posted']
                            else:
                                posted = ''
                    except Exception:
                        posted = ''
                    
                    status = ''
                    try:
                        status = listing.status if hasattr(listing, 'status') else ''
                    except Exception:
                        pass
                    
                    title = 'Unknown'
                    try:
                        title = release.title if hasattr(release, 'title') else 'Unknown'
                    except Exception:
                        pass
                    
                    country = ''
                    try:
                        country = release.country if hasattr(release, 'country') else ''
                    except Exception:
                        pass
                    
                    year = ''
                    try:
                        year = release.year if hasattr(release, 'year') else ''
                    except Exception:
                        pass
                    
                    url = ''
                    try:
                        url = release.url if hasattr(release, 'url') else ''
                    except Exception:
                        pass
                    
                    listings.append({
                        'title': title,
                        'artists': artists_str,
                        'labels': labels_str,
                        'catno': catnos_str,
                        'country': country,
                        'year': year,
                        'genres': genres,
                        'styles': styles,
                        'listing_price': listing_price,
                        'condition': condition,
                        'sleeve_condition': sleeve_condition,
                        'comments': comments,
                        'posted': posted,
                        'status': status,
                        'url': url
                    })
                except Exception as e:
                    print(f"[MARKETPLACE] Error processing listing {idx}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    # Skip problematic listings
                    continue
            
            # Mark as completed
            export_progress[export_id]['status'] = 'completed'
            print(f"[MARKETPLACE] Export completed with {len(listings)} listings")
        
        # Create CSV in memory
        output = io.StringIO()
        csv_columns = ['title', 'artists', 'labels', 'catno', 'country', 'year', 'genres', 'styles', 
                      'listing_price', 'condition', 'sleeve_condition', 'comments', 'posted', 'status', 'url']
        writer = csv.DictWriter(output, fieldnames=csv_columns)
        writer.writeheader()
        for data in listings:
            writer.writerow(data)
        
        # Convert to bytes
        output.seek(0)
        bytes_output = io.BytesIO(output.getvalue().encode('utf-8'))
        bytes_output.seek(0)
        
        # Cleanup progress after delay
        def cleanup():
            time.sleep(5)
            export_progress.pop(export_id, None)
        
        import threading
        threading.Thread(target=cleanup).start()
        
        return send_file(
            bytes_output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'marketplace_inventory_export.csv'
        )
        
    except Exception as e:
        print(f"[MARKETPLACE] Critical error: {str(e)}")
        import traceback
        traceback.print_exc()
        export_progress[export_id]['status'] = 'error'
        export_progress[export_id]['error'] = str(e)
        return f"Export error: {str(e)}", 500


@app.route('/progress_marketplace')
def progress_marketplace():
    """SSE stream for marketplace export progress"""
    def generate():
        username = session.get('username', 'user')
        
        # Wait for export to start (max 10 seconds)
        export_id = None
        for _ in range(20):  # 20 * 0.5s = 10 seconds max
            # Find most recent marketplace export
            for eid in list(export_progress.keys()):
                if eid.startswith(f"{username}_marketplace_"):
                    export_id = eid
                    break
            
            if export_id:
                break
            
            time.sleep(0.5)
            yield f"data: {json.dumps({'status': 'waiting', 'message': 'Waiting...'})}\n\n"
        
        if not export_id:
            yield f"data: {json.dumps({'status': 'error', 'message': 'Export not found'})}\n\n"
            return
        
        # Stream progress
        last_status = None
        while True:
            if export_id not in export_progress:
                # Export cleaned up, it's completed
                if last_status == 'completed':
                    break
                yield f"data: {json.dumps({'status': 'completed', 'current': 0, 'total': 0, 'percent': 100})}\n\n"
                break
            
            progress_data = export_progress[export_id]
            last_status = progress_data['status']
            
            # Calculate estimated time (about 1.5 seconds per listing)
            if progress_data['total'] > 0 and progress_data['current'] > 0:
                progress_percent = (progress_data['current'] / progress_data['total']) * 100
                remaining = progress_data['total'] - progress_data['current']
                estimated_time = int(remaining * 1.5)
            else:
                progress_percent = 0
                estimated_time = int(progress_data.get('total', 0) * 1.5) if progress_data.get('total', 0) > 0 else 0
            
            data = {
                'status': progress_data['status'],
                'current': progress_data['current'],
                'total': progress_data['total'],
                'percent': round(progress_percent, 1),
                'estimated_time': estimated_time,
                'folder_name': progress_data['folder_name']
            }
            
            yield f"data: {json.dumps(data)}\n\n"
            
            if progress_data['status'] in ['completed', 'error']:
                break
            
            time.sleep(0.5)
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/import_cache')
def import_cache_page():
    """Page d'import du cache"""
    if 'access_token' not in session or 'access_secret' not in session:
        return redirect(url_for('index'))
    
    try:
        d = discogs_client.Client('DiscogsExportApp/1.0')
        d.set_consumer_key(CONSUMER_KEY, CONSUMER_SECRET)
        d.set_token(session['access_token'], session['access_secret'])
        me = d.identity()
        
        # Get all folders
        folders_list = []
        collection_folders = me.collection_folders
        for folder in collection_folders:
            folders_list.append({
                'id': folder.id,
                'name': folder.name,
                'count': folder.count
            })
        
        # Get cache statistics
        cache_stats = {'total_cached': 0, 'cached_last_week': 0}
        if db_manager:
            cache_stats = db_manager.get_cache_stats()
        
        return render_template('import_cache.html',
                             username=session.get('username', 'Utilisateur'),
                             folders=folders_list,
                             cache_stats=cache_stats,
                             cache_enabled=db_manager is not None)
    except Exception as e:
        session.clear()
        return redirect(url_for('index'))


@app.route('/start_import', methods=['POST'])
def start_import():
    """Start cache import for selected folders"""
    if 'access_token' not in session or 'access_secret' not in session:
        return {'error': 'Not authenticated'}, 401
    
    if not db_manager:
        return {'error': 'Cache not enabled'}, 400
    
    folder_ids = request.json.get('folder_ids', [])
    if not folder_ids:
        return {'error': 'No folders selected'}, 400
    
    # Create import ID
    import_id = f"{session.get('username', 'user')}_import_{int(time.time())}"
    
    # Get tokens from session before starting thread
    access_token = session['access_token']
    access_secret = session['access_secret']
    
    # Initialize progress
    export_progress[import_id] = {
        'current': 0,
        'total': 0,
        'status': 'starting',
        'folder_name': 'Initializing...',
        'cache_hits': 0,
        'api_calls': 0,
        'errors': 0
    }
    
    # Start import in background thread
    import threading
    
    def run_import():
        try:
            print(f"[IMPORT] Starting import with ID: {import_id}")
            d = discogs_client.Client('DiscogsExportApp/1.0')
            d.set_consumer_key(CONSUMER_KEY, CONSUMER_SECRET)
            d.set_token(access_token, access_secret)
            me = d.identity()
            
            print(f"[IMPORT] Getting folders for user: {me.username}")
            
            # Get selected folders
            collection_folders = list(me.collection_folders)
            selected_folders = [f for f in collection_folders if f.id in folder_ids]
            
            # Calculate total releases
            total_releases = sum(f.count for f in selected_folders)
            export_progress[import_id]['total'] = total_releases
            export_progress[import_id]['status'] = 'processing'
            
            print(f"[IMPORT] Importing {total_releases} releases from {len(selected_folders)} folders")
            
            current_idx = 0
            
            for folder in selected_folders:
                export_progress[import_id]['folder_name'] = folder.name
                print(f"[IMPORT] Processing folder: {folder.name} ({folder.count} releases)")
                
                for collection_item in folder.releases:
                    current_idx += 1
                    export_progress[import_id]['current'] = current_idx
                    
                    release_id = collection_item.id
                    
                    # Check if already in cache
                    cached_data = db_manager.get_cached_release(release_id)
                    if cached_data:
                        export_progress[import_id]['cache_hits'] += 1
                        continue
                    
                    # Rate limiting - 1.1s between API calls
                    if export_progress[import_id]['api_calls'] > 0:
                        time.sleep(1.1)
                    
                    # Fetch from API with retry
                    max_retries = 3
                    retry_delay = 5
                    
                    for retry in range(max_retries):
                        try:
                            release = d.release(release_id)
                            export_progress[import_id]['api_calls'] += 1
                            
                            # Extract release data
                            artists = []
                            for artist in release.artists:
                                artist_filtered_name = re.sub(r'\(.*\)', '', artist.name)
                                artists.append(artist_filtered_name)
                            
                            labels = []
                            catnos = []
                            if hasattr(release, 'labels') and release.labels:
                                for label in release.labels:
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
                            
                            release_data = {
                                'title': release.title if hasattr(release, 'title') else 'Unknown',
                                'artists': artists_str,
                                'labels': labels_str,
                                'catno': catnos_str,
                                'country': release.country if hasattr(release, 'country') else '',
                                'year': str(release.year) if hasattr(release, 'year') else '',
                                'genres': genres,
                                'styles': styles,
                                'price': price,
                                'url': release.url if hasattr(release, 'url') else ''
                            }
                            
                            # Cache the release
                            db_manager.cache_release(release_id, release_data)
                            break  # Success
                            
                        except Exception as e:
                            error_msg = str(e)
                            if 'Expecting value' in error_msg or '429' in error_msg:
                                if retry < max_retries - 1:
                                    wait_time = retry_delay * (retry + 1)
                                    print(f"[IMPORT] Rate limit hit, waiting {wait_time}s (retry {retry + 1}/{max_retries})...")
                                    time.sleep(wait_time)
                                    continue
                                else:
                                    print(f"[IMPORT] Failed after {max_retries} retries: {error_msg}")
                                    export_progress[import_id]['errors'] += 1
                                    break
                            else:
                                print(f"[IMPORT] Error processing release: {error_msg}")
                                export_progress[import_id]['errors'] += 1
                                break
                    
                    # Log progress every 25 items
                    if current_idx % 25 == 0 or current_idx == total_releases:
                        print(f"[IMPORT] Progress: {current_idx}/{total_releases} (cache: {export_progress[import_id]['cache_hits']}, API: {export_progress[import_id]['api_calls']}, errors: {export_progress[import_id]['errors']})")
            
            # Mark as completed
            export_progress[import_id]['status'] = 'completed'
            print(f"[IMPORT] Import completed! Total: {total_releases}, Cache hits: {export_progress[import_id]['cache_hits']}, API calls: {export_progress[import_id]['api_calls']}, Errors: {export_progress[import_id]['errors']}")
            
        except Exception as e:
            print(f"[IMPORT] Critical error: {str(e)}")
            import traceback
            traceback.print_exc()
            export_progress[import_id]['status'] = 'error'
            export_progress[import_id]['error'] = str(e)
    
    thread = threading.Thread(target=run_import)
    thread.daemon = True
    thread.start()
    
    return {'import_id': import_id}, 200


@app.route('/progress_import')
def progress_import():
    """SSE stream for import progress"""
    def generate():
        username = session.get('username', 'user')
        
        # Wait for import to start
        import_id = None
        for _ in range(20):
            for eid in list(export_progress.keys()):
                if eid.startswith(f"{username}_import_"):
                    import_id = eid
                    break
            
            if import_id:
                break
            
            time.sleep(0.5)
            yield f"data: {json.dumps({'status': 'waiting', 'message': 'Starting import...'})}\n\n"
        
        if not import_id:
            yield f"data: {json.dumps({'status': 'error', 'message': 'Import not found'})}\n\n"
            return
        
        # Stream progress
        last_status = None
        while True:
            if import_id not in export_progress:
                if last_status == 'completed':
                    break
                yield f"data: {json.dumps({'status': 'completed', 'current': 0, 'total': 0, 'percent': 100})}\n\n"
                break
            
            progress_data = export_progress[import_id]
            last_status = progress_data['status']
            
            # Calculate progress
            if progress_data['total'] > 0 and progress_data['current'] > 0:
                progress_percent = (progress_data['current'] / progress_data['total']) * 100
                remaining = progress_data['total'] - progress_data['current']
                estimated_time = int(remaining * 1.1)  # 1.1s per release
            else:
                progress_percent = 0
                estimated_time = int(progress_data.get('total', 0) * 1.1)
            
            data = {
                'status': progress_data['status'],
                'current': progress_data['current'],
                'total': progress_data['total'],
                'percent': round(progress_percent, 1),
                'estimated_time': estimated_time,
                'folder_name': progress_data['folder_name'],
                'cache_hits': progress_data.get('cache_hits', 0),
                'api_calls': progress_data.get('api_calls', 0),
                'errors': progress_data.get('errors', 0)
            }
            
            yield f"data: {json.dumps(data)}\n\n"
            
            if progress_data['status'] in ['completed', 'error']:
                # Cleanup after delay
                def cleanup():
                    time.sleep(5)
                    export_progress.pop(import_id, None)
                
                import threading
                threading.Thread(target=cleanup).start()
                break
            
            time.sleep(0.5)
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/logout')
def logout():
    """Déconnexion"""
    session.clear()
    return redirect(url_for('index'))


# Intégration Batch Processor
from batch_flask_integration import create_batch_blueprint
batch_bp = create_batch_blueprint(app)
app.register_blueprint(batch_bp)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
