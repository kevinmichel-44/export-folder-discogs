"""
Example Flask integration for batch_processor.py

This demonstrates how to integrate the batch processor with the existing Flask app
without modifying the original code.

Usage:
1. Import this module in your Flask app
2. Use the batch_export endpoint for optimized exports
3. Monitor progress via the batch_progress endpoint
"""

from flask import Flask, jsonify, request, Response, session
from batch_processor import BatchProcessor, WorkerPool
import discogs_client
from database import DatabaseManager
import uuid
import json
import time
from typing import Dict
import io
import csv


# Global storage for batch jobs
batch_jobs: Dict[str, Dict] = {}


def create_batch_blueprint(app: Flask):
    """
    Create a Flask blueprint with batch processing endpoints
    
    This can be registered to the existing Flask app without modifying it.
    """
    from flask import Blueprint
    
    bp = Blueprint('batch', __name__, url_prefix='/batch')
    
    @bp.route('/export/<folder_id>', methods=['POST'])
    def batch_export(folder_id):
        """
        Start a batch export with optimized worker queue
        
        POST data:
        {
            "num_workers": 3,     // Optional, default 3
            "rate_limit": 60,     // Optional, default 60 req/min
            "priority": 5         // Optional, default 5
        }
        """
        # Get OAuth tokens
        access_token = session.get('access_token')
        access_secret = session.get('access_secret')
        
        if not access_token or not access_secret:
            return jsonify({'error': 'Not authenticated'}), 401
        
        # Parse request options
        options = request.get_json() or {}
        num_workers = options.get('num_workers', 3)
        rate_limit = options.get('rate_limit', 60)
        priority = options.get('priority', 5)
        
        # Initialize Discogs client
        user_agent = 'ExportFolderDiscogs/1.0'
        import os
        consumer_key = os.environ.get('DISCOGS_CONSUMER_KEY', '')
        consumer_secret = os.environ.get('DISCOGS_CONSUMER_SECRET', '')
        
        if not consumer_key or not consumer_secret:
            return jsonify({'error': 'OAuth configuration missing'}), 500
        
        d = discogs_client.Client(
            user_agent,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            token=access_token,
            secret=access_secret
        )
        
        # Get folder
        try:
            me = d.identity()
            folders = me.collection_folders
            
            folder = None
            for f in folders:
                if str(f.id) == str(folder_id):
                    folder = f
                    break
            
            if not folder:
                return jsonify({'error': 'Folder not found'}), 404
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        
        # Create batch job
        batch_id = str(uuid.uuid4())
        
        # Initialize database manager
        db_manager = DatabaseManager()
        
        # Create batch processor
        processor = BatchProcessor(
            d,
            db_manager,
            num_workers=num_workers,
            rate_limit=rate_limit
        )
        
        # Collect release IDs with rate limiting
        print(f"[BATCH] Collecting release IDs from folder {folder.name} ({folder.count} releases)")
        release_ids = []
        try:
            # Iterate carefully to avoid rate limiting
            for idx, item in enumerate(folder.releases):
                release_ids.append(item.id)
                # Small delay every 50 items to avoid overwhelming the API
                if (idx + 1) % 50 == 0:
                    print(f"[BATCH] Collected {idx + 1}/{folder.count} release IDs")
                    time.sleep(0.5)
        except Exception as e:
            print(f"[BATCH] Error collecting release IDs: {e}")
            if not release_ids:
                return jsonify({'error': f'Failed to collect release IDs: {str(e)}'}), 500
            print(f"[BATCH] Continuing with {len(release_ids)} releases collected so far")
        
        # Storage for results
        results = []
        results_lock = __import__('threading').Lock()
        
        # Store job info BEFORE starting
        batch_jobs[batch_id] = {
            'id': batch_id,
            'folder_id': folder_id,
            'folder_name': folder.name,
            'total': len(release_ids),
            'processed': 0,
            'status': 'starting',
            'start_time': time.time(),
            'last_update': time.time(),
            'results': results,
            'processor': processor
        }
        
        def on_result(release_id, data, metadata):
            """Callback to store results"""
            with results_lock:
                if data:
                    results.append(data)
                
                # Update job progress  
                if batch_id in batch_jobs:
                    batch_jobs[batch_id]['processed'] = len(results)
                    batch_jobs[batch_id]['last_update'] = time.time()
        
        # Start processing in background thread
        def run_batch():
            try:
                batch_jobs[batch_id]['status'] = 'processing'
                
                stats = processor.process_releases(
                    release_ids,
                    callback=on_result,
                    priority=priority
                )
                
                batch_jobs[batch_id]['status'] = 'completed'
                batch_jobs[batch_id]['stats'] = stats
                batch_jobs[batch_id]['end_time'] = time.time()
                
            except Exception as e:
                batch_jobs[batch_id]['status'] = 'error'
                batch_jobs[batch_id]['error'] = str(e)
        
        import threading
        thread = threading.Thread(target=run_batch, daemon=True)
        thread.start()
        
        return jsonify({
            'batch_id': batch_id,
            'folder_id': folder_id,
            'folder_name': folder.name,
            'total_releases': len(release_ids),
            'num_workers': num_workers
        })
    
    @bp.route('/progress/<batch_id>')
    def batch_progress(batch_id):
        """
        Get progress of a batch job (SSE endpoint)
        """
        if batch_id not in batch_jobs:
            return jsonify({'error': 'Batch job not found'}), 404
        
        def generate():
            while True:
                if batch_id not in batch_jobs:
                    break
                
                job = batch_jobs[batch_id]
                stats = job.get('stats', {})
                
                # Get current progress
                completed = stats.get('completed', job.get('processed', 0))
                
                data = {
                    'batch_id': batch_id,
                    'status': job['status'],
                    'total': job['total'],
                    'completed': completed,
                    'processed': job.get('processed', 0),
                    'folder_name': job['folder_name'],
                    'cache_hits': stats.get('cache_hits', 0),
                    'api_calls': stats.get('api_calls', 0),
                    'failed': stats.get('failed', 0),
                    'message': f"Processing {completed}/{job['total']} releases..."
                }
                
                # Calculate ETA
                if completed > 0 and job['total'] > 0:
                    elapsed = time.time() - job['start_time']
                    rate = completed / elapsed
                    remaining = job['total'] - completed
                    eta = remaining / rate if rate > 0 else 0
                    data['eta'] = eta
                else:
                    data['eta'] = 0
                
                yield f"event: progress\ndata: {json.dumps(data)}\n\n"
                
                # If completed, send final stats and stop
                if job['status'] == 'completed':
                    data['message'] = 'Export completed!'
                    yield f"event: complete\ndata: {json.dumps(data)}\n\n"
                    break
                
                # If error, send error and stop
                if job['status'] == 'error':
                    data['error'] = job.get('error', 'Unknown error')
                    data['message'] = 'Export failed'
                    yield f"event: error\ndata: {json.dumps(data)}\n\n"
                    break
                
                time.sleep(0.5)
        
        return Response(generate(), mimetype='text/event-stream')
    
    @bp.route('/download/<batch_id>')
    def batch_download(batch_id):
        """
        Download results as CSV
        """
        if batch_id not in batch_jobs:
            return jsonify({'error': 'Batch job not found'}), 404
        
        job = batch_jobs[batch_id]
        
        if job['status'] != 'completed':
            return jsonify({'error': 'Batch job not completed'}), 400
        
        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            'Artists', 'Title', 'Label', 'Catalog Number',
            'Country', 'Year', 'Genres', 'Styles', 'Price', 'URL'
        ])
        
        # Data
        for data in job['results']:
            writer.writerow([
                data['artists'],
                data['title'],
                data['labels'],
                data['catno'],
                data['country'],
                data['year'],
                data['genres'],
                data['styles'],
                data['price'],
                data['url']
            ])
        
        # Create response
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=discogs_export_{job["folder_name"]}_{batch_id[:8]}.csv'
            }
        )
    
    @bp.route('/status/<batch_id>')
    def batch_status(batch_id):
        """
        Get status of a batch job (JSON)
        """
        if batch_id not in batch_jobs:
            return jsonify({'error': 'Batch job not found'}), 404
        
        job = batch_jobs[batch_id]
        
        response = {
            'batch_id': batch_id,
            'status': job['status'],
            'total': job['total'],
            'processed': job['processed'],
            'folder_name': job['folder_name'],
            'start_time': job['start_time']
        }
        
        if 'end_time' in job:
            response['end_time'] = job['end_time']
            response['duration'] = job['end_time'] - job['start_time']
        
        if 'stats' in job:
            response['stats'] = {
                'cache_hits': job['stats'].get('cache_hits', 0),
                'api_calls': job['stats'].get('api_calls', 0),
                'failed': job['stats'].get('failed', 0),
                'retries': job['stats'].get('retries', 0)
            }
        
        if 'error' in job:
            response['error'] = job['error']
        
        return jsonify(response)
    
    @bp.route('/cancel/<batch_id>', methods=['POST'])
    def batch_cancel(batch_id):
        """
        Cancel a running batch job
        """
        if batch_id not in batch_jobs:
            return jsonify({'error': 'Batch job not found'}), 404
        
        job = batch_jobs[batch_id]
        
        if job['status'] not in ['starting', 'processing']:
            return jsonify({'error': 'Cannot cancel completed job'}), 400
        
        # Stop the processor
        if 'processor' in job:
            job['processor'].pool.stop(wait=False)
        
        job['status'] = 'cancelled'
        
        return jsonify({'message': 'Batch job cancelled'})
    
    @bp.route('/list')
    def batch_list():
        """
        Display batch export page with folder list
        """
        from flask import render_template
        
        # Get user info from session
        if 'access_token' not in session or 'access_secret' not in session:
            from flask import redirect, url_for
            return redirect(url_for('index'))
        
        # Get Discogs client
        user_agent = 'DiscogsExporter/1.0'
        import os
        consumer_key = os.environ.get('DISCOGS_CONSUMER_KEY', '')
        consumer_secret = os.environ.get('DISCOGS_CONSUMER_SECRET', '')
        
        d = discogs_client.Client(
            user_agent,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            token=session['access_token'],
            secret=session['access_secret']
        )
        
        # Get username and folders
        me = d.identity()
        username = me.username
        folders = me.collection_folders
        
        # Get cache stats
        db_manager = DatabaseManager()
        cache_stats = db_manager.get_cache_stats()
        
        return render_template('batch_export.html',
                             username=username,
                             folders=folders,
                             cache_stats=cache_stats)
    
    @bp.route('/list/json')
    def batch_list_json():
        """
        List all batch jobs (JSON API)
        """
        jobs_list = []
        
        for batch_id, job in batch_jobs.items():
            # Get stats safely
            stats = job.get('stats', {})
            
            jobs_list.append({
                'batch_id': batch_id,
                'folder_id': job['folder_id'],
                'folder_name': job.get('folder_name', ''),
                'status': job['status'],
                'total': job['total'],
                'completed': stats.get('completed', job.get('processed', 0)),
                'cache_hits': stats.get('cache_hits', 0),
                'api_calls': stats.get('api_calls', 0),
                'failed': stats.get('failed', 0),
                'started_at': job['start_time'],
                'completed_at': job.get('end_time')
            })
        
        return jsonify({'jobs': jobs_list})
    
    return bp


# Example HTML template for batch export UI
BATCH_EXPORT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Batch Export - {{ folder_name }}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .progress { width: 100%; background: #f0f0f0; border-radius: 5px; }
        .progress-bar { 
            height: 30px; 
            background: #4CAF50; 
            border-radius: 5px;
            transition: width 0.3s;
            line-height: 30px;
            color: white;
            text-align: center;
        }
        .stats { margin-top: 20px; }
        .stats div { margin: 5px 0; }
        .button {
            padding: 10px 20px;
            background: #2196F3;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            margin: 5px;
        }
        .button:disabled { background: #ccc; cursor: not-allowed; }
        .options { margin-bottom: 20px; }
        .options label { display: block; margin: 10px 0 5px 0; }
        .options input { width: 200px; padding: 5px; }
    </style>
</head>
<body>
    <h1>Batch Export: {{ folder_name }}</h1>
    
    <div class="options">
        <label>Number of Workers (1-5):</label>
        <input type="number" id="num_workers" value="3" min="1" max="5">
        
        <label>Rate Limit (requests/min):</label>
        <input type="number" id="rate_limit" value="60" min="30" max="60">
    </div>
    
    <button id="startBtn" class="button" onclick="startBatch()">Start Batch Export</button>
    <button id="cancelBtn" class="button" onclick="cancelBatch()" disabled>Cancel</button>
    
    <div id="progress-container" style="display: none; margin-top: 20px;">
        <h3>Progress: <span id="status">Starting...</span></h3>
        <div class="progress">
            <div id="progress-bar" class="progress-bar" style="width: 0%;">0%</div>
        </div>
        
        <div class="stats">
            <div><strong>Processed:</strong> <span id="processed">0</span> / <span id="total">0</span></div>
            <div><strong>Cache Hits:</strong> <span id="cache_hits">0</span></div>
            <div><strong>API Calls:</strong> <span id="api_calls">0</span></div>
            <div><strong>Failed:</strong> <span id="failed">0</span></div>
            <div><strong>Duration:</strong> <span id="duration">0s</span></div>
        </div>
    </div>
    
    <div id="download-container" style="display: none; margin-top: 20px;">
        <button class="button" onclick="downloadResults()">Download CSV</button>
    </div>
    
    <script>
        let batchId = null;
        let eventSource = null;
        let startTime = null;
        
        function startBatch() {
            const numWorkers = document.getElementById('num_workers').value;
            const rateLimit = document.getElementById('rate_limit').value;
            
            document.getElementById('startBtn').disabled = true;
            document.getElementById('progress-container').style.display = 'block';
            
            startTime = Date.now();
            
            fetch('/batch/export/{{ folder_id }}', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    num_workers: parseInt(numWorkers),
                    rate_limit: parseInt(rateLimit)
                })
            })
            .then(r => r.json())
            .then(data => {
                batchId = data.batch_id;
                document.getElementById('total').textContent = data.total_releases;
                document.getElementById('cancelBtn').disabled = false;
                
                // Start listening for progress
                eventSource = new EventSource('/batch/progress/' + batchId);
                eventSource.onmessage = function(e) {
                    const data = JSON.parse(e.data);
                    updateProgress(data);
                    
                    if (data.status === 'completed') {
                        eventSource.close();
                        document.getElementById('cancelBtn').disabled = true;
                        document.getElementById('download-container').style.display = 'block';
                    } else if (data.status === 'error') {
                        eventSource.close();
                        alert('Error: ' + data.error);
                    }
                };
            })
            .catch(err => {
                alert('Error: ' + err);
                document.getElementById('startBtn').disabled = false;
            });
        }
        
        function updateProgress(data) {
            const percent = (data.processed / data.total) * 100;
            document.getElementById('progress-bar').style.width = percent + '%';
            document.getElementById('progress-bar').textContent = Math.round(percent) + '%';
            
            document.getElementById('status').textContent = data.status;
            document.getElementById('processed').textContent = data.processed;
            
            if (data.stats) {
                document.getElementById('cache_hits').textContent = data.stats.cache_hits || 0;
                document.getElementById('api_calls').textContent = data.stats.api_calls || 0;
                document.getElementById('failed').textContent = data.stats.failed || 0;
            }
            
            const duration = (Date.now() - startTime) / 1000;
            document.getElementById('duration').textContent = duration.toFixed(1) + 's';
        }
        
        function cancelBatch() {
            if (!batchId) return;
            
            fetch('/batch/cancel/' + batchId, { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                alert(data.message);
                if (eventSource) eventSource.close();
                document.getElementById('cancelBtn').disabled = true;
            });
        }
        
        function downloadResults() {
            window.location.href = '/batch/download/' + batchId;
        }
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    """
    Example of how to integrate with Flask app
    """
    print("""
    To integrate batch processing into your Flask app:
    
    1. Import the blueprint creator:
       from batch_flask_integration import create_batch_blueprint
    
    2. Register the blueprint:
       batch_bp = create_batch_blueprint(app)
       app.register_blueprint(batch_bp)
    
    3. Add links to your templates:
       <a href="/batch/export/{{ folder_id }}">Batch Export (Optimized)</a>
    
    4. New endpoints available:
       - POST /batch/export/<folder_id> - Start batch export
       - GET /batch/progress/<batch_id> - Progress SSE
       - GET /batch/download/<batch_id> - Download CSV
       - GET /batch/status/<batch_id> - Get status JSON
       - POST /batch/cancel/<batch_id> - Cancel job
       - GET /batch/list - List all jobs
    """)
