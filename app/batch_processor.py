"""
Batch Request Processor with Worker Queue and Token Bucket Rate Limiting

This module provides an optimized batch processing system for Discogs API calls
using a worker queue pattern and token bucket algorithm for rate limiting.

Features:
- Token Bucket algorithm for smooth rate limiting
- Worker queue with configurable concurrency
- Batch processing of releases
- Priority queue support
- Automatic retry with exponential backoff
- Progress tracking and statistics
"""

import time
import threading
from queue import Queue, PriorityQueue, Empty
from dataclasses import dataclass, field
from typing import Optional, Callable, Any, Dict, List
from datetime import datetime
import discogs_client
from database import DatabaseManager


class TokenBucket:
    """
    Token Bucket Algorithm for rate limiting
    
    Allows bursts while maintaining average rate limit.
    Discogs API: 60 requests per minute = 1 token per second
    """
    
    def __init__(self, capacity: int = 60, refill_rate: float = 1.0):
        """
        Args:
            capacity: Maximum number of tokens (60 for Discogs API)
            refill_rate: Tokens added per second (1.0 = 60/min)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()
        self.lock = threading.Lock()
    
    def _refill(self):
        """Refill tokens based on elapsed time"""
        now = time.time()
        elapsed = now - self.last_refill
        tokens_to_add = elapsed * self.refill_rate
        
        if tokens_to_add > 0:
            self.tokens = min(self.capacity, self.tokens + tokens_to_add)
            self.last_refill = now
    
    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            True if tokens were consumed, False otherwise
        """
        with self.lock:
            self._refill()
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    def wait_for_token(self, tokens: int = 1, timeout: Optional[float] = None):
        """
        Wait until tokens are available
        
        Args:
            tokens: Number of tokens needed
            timeout: Maximum time to wait (None = infinite)
        """
        start_time = time.time()
        
        while True:
            if self.consume(tokens):
                return True
            
            if timeout and (time.time() - start_time) > timeout:
                return False
            
            # Sleep for a fraction of the time needed
            with self.lock:
                self._refill()
                tokens_needed = tokens - self.tokens
                wait_time = tokens_needed / self.refill_rate
                time.sleep(min(0.1, wait_time))


@dataclass(order=True)
class Task:
    """Task for processing queue"""
    priority: int
    release_id: int = field(compare=False)
    callback: Optional[Callable] = field(default=None, compare=False)
    retry_count: int = field(default=0, compare=False)
    metadata: Dict[str, Any] = field(default_factory=dict, compare=False)


class WorkerPool:
    """
    Worker pool with token bucket rate limiting
    
    Manages multiple worker threads that process tasks from a queue
    while respecting API rate limits using token bucket algorithm.
    """
    
    def __init__(
        self,
        num_workers: int = 1,
        rate_limit_capacity: int = 60,
        rate_limit_refill: float = 1.0,
        max_retries: int = 2,
        retry_delay: float = 10.0
    ):
        """
        Args:
            num_workers: Number of concurrent workers
            rate_limit_capacity: Token bucket capacity
            rate_limit_refill: Tokens per second
            max_retries: Maximum retry attempts per task
            retry_delay: Base delay between retries (exponential backoff)
        """
        self.num_workers = num_workers
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # Token bucket for rate limiting
        self.token_bucket = TokenBucket(rate_limit_capacity, rate_limit_refill)
        
        # Task queue (priority queue)
        self.task_queue = PriorityQueue()
        
        # Workers
        self.workers = []
        self.running = False
        
        # Statistics
        self.stats = {
            'total_tasks': 0,
            'completed': 0,
            'failed': 0,
            'cache_hits': 0,
            'api_calls': 0,
            'retries': 0,
            'start_time': None,
            'end_time': None
        }
        self.stats_lock = threading.Lock()
    
    def add_task(
        self,
        release_id: int,
        priority: int = 5,
        callback: Optional[Callable] = None,
        metadata: Optional[Dict] = None
    ):
        """
        Add a task to the queue
        
        Args:
            release_id: Discogs release ID to fetch
            priority: Task priority (lower = higher priority)
            callback: Function to call with result
            metadata: Additional data to pass to callback
        """
        task = Task(
            priority=priority,
            release_id=release_id,
            callback=callback,
            metadata=metadata or {}
        )
        self.task_queue.put(task)
        
        with self.stats_lock:
            self.stats['total_tasks'] += 1
    
    def _worker_loop(
        self,
        worker_id: int,
        discogs_client_instance: discogs_client.Client,
        db_manager: DatabaseManager
    ):
        """
        Worker thread main loop
        
        Args:
            worker_id: Worker identifier
            discogs_client_instance: Discogs API client
            db_manager: Database manager for caching
        """
        print(f"[WORKER-{worker_id}] Started")
        
        while self.running:
            try:
                # Get task with timeout
                task = self.task_queue.get(timeout=1.0)
            except Empty:
                continue
            
            try:
                # Check cache first
                cached_data = db_manager.get_cached_release(task.release_id)
                
                if cached_data:
                    with self.stats_lock:
                        self.stats['cache_hits'] += 1
                    
                    print(f"[WORKER-{worker_id}] Cache hit for release {task.release_id}")
                    
                    # Call callback with cached data
                    if task.callback:
                        task.callback(task.release_id, cached_data, task.metadata)
                    
                    with self.stats_lock:
                        self.stats['completed'] += 1
                    
                    self.task_queue.task_done()
                    continue
                
                # Not in cache - wait for token
                self.token_bucket.wait_for_token(1)
                
                # Fetch from API
                try:
                    release = discogs_client_instance.release(task.release_id)
                    
                    with self.stats_lock:
                        self.stats['api_calls'] += 1
                    
                    # Extract data
                    artists = []
                    for artist in release.artists:
                        import re
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
                            
                            import re
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
                    
                    # Cache the result
                    db_manager.cache_release(task.release_id, release_data)
                    
                    print(f"[WORKER-{worker_id}] Fetched release {task.release_id}: {release_data['title']}")
                    
                    # Call callback
                    if task.callback:
                        task.callback(task.release_id, release_data, task.metadata)
                    
                    with self.stats_lock:
                        self.stats['completed'] += 1
                
                except Exception as e:
                    error_msg = str(e)
                    
                    # Check if should retry
                    if task.retry_count < self.max_retries and ('429' in error_msg or 'Expecting value' in error_msg):
                        task.retry_count += 1
                        wait_time = self.retry_delay * task.retry_count
                        
                        print(f"[WORKER-{worker_id}] Retry {task.retry_count}/{self.max_retries} for release {task.release_id} after {wait_time}s")
                        
                        with self.stats_lock:
                            self.stats['retries'] += 1
                        
                        time.sleep(wait_time)
                        self.task_queue.put(task)
                    else:
                        print(f"[WORKER-{worker_id}] Failed to fetch release {task.release_id}: {error_msg}")
                        
                        with self.stats_lock:
                            self.stats['failed'] += 1
                        
                        # Call callback with None to signal failure
                        if task.callback:
                            task.callback(task.release_id, None, task.metadata)
                
                self.task_queue.task_done()
            
            except Exception as e:
                print(f"[WORKER-{worker_id}] Unexpected error: {str(e)}")
                self.task_queue.task_done()
        
        print(f"[WORKER-{worker_id}] Stopped")
    
    def start(
        self,
        discogs_client_instance: discogs_client.Client,
        db_manager: DatabaseManager
    ):
        """
        Start the worker pool
        
        Args:
            discogs_client_instance: Discogs API client
            db_manager: Database manager
        """
        if self.running:
            print("[POOL] Already running")
            return
        
        self.running = True
        self.stats['start_time'] = datetime.now()
        
        # Create workers
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                args=(i, discogs_client_instance, db_manager),
                daemon=True
            )
            worker.start()
            self.workers.append(worker)
        
        print(f"[POOL] Started with {self.num_workers} workers")
    
    def stop(self, wait: bool = True):
        """
        Stop the worker pool
        
        Args:
            wait: If True, wait for all tasks to complete
        """
        if not self.running:
            return
        
        if wait:
            print("[POOL] Waiting for tasks to complete...")
            self.task_queue.join()
        
        self.running = False
        self.stats['end_time'] = datetime.now()
        
        # Wait for workers to finish
        for worker in self.workers:
            worker.join(timeout=2.0)
        
        self.workers.clear()
        print("[POOL] Stopped")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        with self.stats_lock:
            stats_copy = self.stats.copy()
        
        if stats_copy['start_time'] and stats_copy['end_time']:
            duration = (stats_copy['end_time'] - stats_copy['start_time']).total_seconds()
            stats_copy['duration_seconds'] = duration
            
            if duration > 0:
                stats_copy['tasks_per_second'] = stats_copy['completed'] / duration
        
        return stats_copy
    
    def print_stats(self):
        """Print processing statistics"""
        stats = self.get_stats()
        
        print("\n[POOL] Processing Statistics:")
        print(f"  Total tasks: {stats['total_tasks']}")
        print(f"  Completed: {stats['completed']}")
        print(f"  Failed: {stats['failed']}")
        print(f"  Cache hits: {stats['cache_hits']}")
        print(f"  API calls: {stats['api_calls']}")
        print(f"  Retries: {stats['retries']}")
        
        if 'duration_seconds' in stats:
            print(f"  Duration: {stats['duration_seconds']:.2f}s")
            print(f"  Speed: {stats.get('tasks_per_second', 0):.2f} tasks/s")
        
        print(f"  Queue size: {self.task_queue.qsize()}")


class BatchProcessor:
    """
    High-level batch processor for Discogs releases
    
    Simplifies batch processing with automatic worker management.
    """
    
    def __init__(
        self,
        discogs_client_instance: discogs_client.Client,
        db_manager: DatabaseManager,
        num_workers: int = 3,
        rate_limit: int = 60
    ):
        """
        Args:
            discogs_client_instance: Discogs API client
            db_manager: Database manager
            num_workers: Number of concurrent workers
            rate_limit: API rate limit (requests per minute)
        """
        self.client = discogs_client_instance
        self.db_manager = db_manager
        
        self.pool = WorkerPool(
            num_workers=num_workers,
            rate_limit_capacity=rate_limit,
            rate_limit_refill=rate_limit / 60.0  # Convert to per second
        )
    
    def process_releases(
        self,
        release_ids: List[int],
        callback: Optional[Callable] = None,
        priority: int = 5
    ) -> Dict[str, Any]:
        """
        Process a batch of releases
        
        Args:
            release_ids: List of Discogs release IDs
            callback: Function to call for each result
            priority: Priority for all tasks
            
        Returns:
            Processing statistics
        """
        print(f"[BATCH] Starting batch processing of {len(release_ids)} releases")
        
        # Start pool
        self.pool.start(self.client, self.db_manager)
        
        # Add all tasks
        for release_id in release_ids:
            self.pool.add_task(release_id, priority=priority, callback=callback)
        
        # Wait for completion
        self.pool.stop(wait=True)
        
        # Get and print statistics
        stats = self.pool.get_stats()
        self.pool.print_stats()
        
        return stats


# Example usage
if __name__ == "__main__":
    """
    Example usage of batch processor
    """
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Initialize clients
    user_agent = 'ExportFolderDiscogs/1.0'
    consumer_key = os.getenv('CONSUMER_KEY')
    consumer_secret = os.getenv('CONSUMER_SECRET')
    
    # You would need to get these from OAuth flow
    # access_token = os.getenv('ACCESS_TOKEN')
    # access_secret = os.getenv('ACCESS_SECRET')
    
    # d = discogs_client.Client(
    #     user_agent,
    #     consumer_key=consumer_key,
    #     consumer_secret=consumer_secret,
    #     token=access_token,
    #     secret=access_secret
    # )
    
    # db_manager = DatabaseManager()
    
    # # Create batch processor
    # processor = BatchProcessor(d, db_manager, num_workers=3, rate_limit=60)
    
    # # Define callback
    # def on_result(release_id, data, metadata):
    #     if data:
    #         print(f"Got result for {release_id}: {data['title']}")
    #     else:
    #         print(f"Failed to get {release_id}")
    
    # # Process releases
    # release_ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]  # Example IDs
    # stats = processor.process_releases(release_ids, callback=on_result)
    
    print("Example code - uncomment to run with valid credentials")
