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

# Charger les variables d'environnement
load_dotenv()

# Configurer les logs pour ignorer les erreurs SSL en dev
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
app.permanent_session_lifetime = timedelta(hours=2)

# Configuration OAuth Discogs
# Obtenez vos clés sur https://www.discogs.com/settings/developers
CONSUMER_KEY = os.environ.get('DISCOGS_CONSUMER_KEY', '')
CONSUMER_SECRET = os.environ.get('DISCOGS_CONSUMER_SECRET', '')
CALLBACK_URL = os.environ.get('CALLBACK_URL', 'http://127.0.0.1:5000/callback')

# Stockage temporaire pour la progression
export_progress = {}


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
                total_releases = folder.count
                
                # Mettre à jour la progression
                export_progress[export_id]['total'] = total_releases
                export_progress[export_id]['folder_name'] = folder_name
                export_progress[export_id]['status'] = 'processing'
                
                # Récupérer toutes les releases du dossier
                for idx, collection_item in enumerate(folder.releases, 1):
                    # Mettre à jour la progression
                    export_progress[export_id]['current'] = idx
                    
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
                
                # Marquer comme terminé
                export_progress[export_id]['status'] = 'completed'
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


@app.route('/logout')
def logout():
    """Déconnexion"""
    session.clear()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
