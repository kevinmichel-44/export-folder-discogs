#!/usr/bin/env python3
"""
Import all Discogs data dumps (artists, labels, masters, releases)
Downloads and imports monthly XML dumps from Discogs S3 bucket
"""
import os
import sys
import gzip
import argparse
import requests
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET

# Add parent directory to path to import database module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
from database import DatabaseManager, CachedRelease, CachedArtist, CachedLabel, CachedMaster

# Dump types configuration
DUMP_TYPES = {
    'artists': {
        'prefix': 'discogs_',
        'suffix': '_artists.xml.gz',
        'model': CachedArtist,
        'tag': 'artist'
    },
    'labels': {
        'prefix': 'discogs_',
        'suffix': '_labels.xml.gz',
        'model': CachedLabel,
        'tag': 'label'
    },
    'masters': {
        'prefix': 'discogs_',
        'suffix': '_masters.xml.gz',
        'model': CachedMaster,
        'tag': 'master'
    },
    'releases': {
        'prefix': 'discogs_',
        'suffix': '_releases.xml.gz',
        'model': CachedRelease,
        'tag': 'release'
    }
}

S3_BASE_URL = 'https://discogs-data-dumps.s3.us-west-2.amazonaws.com/data'


def get_latest_dump_url(dump_type, year_month=None):
    """
    Find the latest dump URL for a given type
    
    Args:
        dump_type: One of 'artists', 'labels', 'masters', 'releases'
        year_month: Optional specific year (e.g., '2026') to use
    
    Returns:
        tuple: (url, filename) or (None, None) if not found
    """
    config = DUMP_TYPES[dump_type]
    
    # Try current year by default
    if year_month is None:
        now = datetime.now()
        year_month = str(now.year)
    
    # Remove any slashes from year_month
    year = year_month.replace('/', '')
    
    # Build expected filename (e.g., discogs_20260101_artists.xml.gz)
    filename = f"{config['prefix']}{year}0101{config['suffix']}"
    url = f"{S3_BASE_URL}/{year}/{filename}"
    
    print(f"[{dump_type.upper()}] Checking URL: {url}")
    
    # Check if URL exists
    try:
        response = requests.head(url, timeout=10)
        if response.status_code == 200:
            size_mb = int(response.headers.get('Content-Length', 0)) / (1024 * 1024)
            print(f"[{dump_type.upper()}] Found dump: {filename} ({size_mb:.1f} MB)")
            return url, filename
    except Exception as e:
        print(f"[{dump_type.upper()}] Error checking URL: {e}")
    
    return None, None


def download_dump(url, filename, output_dir='data/dumps'):
    """
    Download a dump file from URL with progress bar
    
    Args:
        url: URL to download from
        filename: Name of the file
        output_dir: Directory to save to
    
    Returns:
        Path to downloaded file or None on error
    """
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    
    # Skip if already exists
    if os.path.exists(filepath):
        print(f"[DOWNLOAD] File already exists: {filepath}")
        return filepath
    
    print(f"[DOWNLOAD] Downloading {filename}...")
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        block_size = 8192
        downloaded = 0
        
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=block_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        print(f"\r[DOWNLOAD] Progress: {progress:.1f}% ({downloaded/(1024*1024):.1f} MB)", end='')
        
        print(f"\n[DOWNLOAD] Downloaded successfully: {filepath}")
        return filepath
    
    except Exception as e:
        print(f"\n[DOWNLOAD] Error downloading {filename}: {e}")
        if os.path.exists(filepath):
            os.remove(filepath)
        return None


def parse_artists_dump(filepath, db_manager, limit=None):
    """Parse artists dump and import to database"""
    print(f"[ARTISTS] Parsing {filepath}...")
    
    session = db_manager.Session()
    count = 0
    skipped = 0
    batch = []
    batch_size = 5000
    
    # Désactiver autoflush pour plus de performance
    session.autoflush = False
    session.autocommit = False
    
    try:
        with gzip.open(filepath, 'rt', encoding='utf-8') as f:
            context = ET.iterparse(f, events=('start', 'end'))
            context = iter(context)
            event, root = next(context)
            
            for event, elem in context:
                if event == 'end' and elem.tag == 'artist':
                    try:
                        artist_id = int(elem.find('id').text) if elem.find('id') is not None else None
                        if not artist_id:
                            continue
                        
                        # Check if exists
                        exists = session.query(CachedArtist).filter_by(id=artist_id).first()
                        if exists:
                            skipped += 1
                            elem.clear()
                            continue
                        
                        # Extract data
                        name = elem.find('name').text if elem.find('name') is not None else ''
                        real_name = elem.find('realname').text if elem.find('realname') is not None else ''
                        profile = elem.find('profile').text if elem.find('profile') is not None else ''
                        
                        # URLs
                        urls = [url.text for url in elem.findall('.//url') if url.text]
                        
                        # Name variations
                        namevariations = [nv.text for nv in elem.findall('.//namevariations/name') if nv.text]
                        
                        # Aliases
                        aliases = [alias.get('name') for alias in elem.findall('.//aliases/name') if alias.get('name')]
                        
                        artist = CachedArtist(
                            id=artist_id,
                            name=name[:500] if name else '',
                            real_name=real_name[:500] if real_name else '',
                            profile=profile,
                            urls=','.join(urls),
                            name_variations=','.join(namevariations),
                            aliases=','.join(aliases)
                        )
                        
                        batch.append(artist)
                        count += 1
                        
                        # Batch insert
                        if len(batch) >= batch_size:
                            session.bulk_save_objects(batch)
                            session.commit()
                            batch = []
                            print(f"\r[ARTISTS] Imported: {count:,} (skipped: {skipped:,})", end='')
                        
                        if limit and count >= limit:
                            break
                    
                    except Exception as e:
                        print(f"\n[ARTISTS] Error parsing artist: {e}")
                    
                    finally:
                        elem.clear()
                        root.clear()
        
        # Insert remaining
        if batch:
            session.bulk_save_objects(batch)
            session.commit()
        
        print(f"\n[ARTISTS] ✓ Import complete: {count:,} artists imported, {skipped:,} skipped")
        return count
    
    except Exception as e:
        print(f"\n[ARTISTS] Error: {e}")
        session.rollback()
        return 0
    finally:
        session.close()


def parse_labels_dump(filepath, db_manager, limit=None):
    """Parse labels dump and import to database"""
    print(f"[LABELS] Parsing {filepath}...")
    
    session = db_manager.Session()
    count = 0
    skipped = 0
    batch = []
    batch_size = 5000
    
    # Désactiver autoflush pour plus de performance
    session.autoflush = False
    session.autocommit = False
    
    try:
        with gzip.open(filepath, 'rt', encoding='utf-8') as f:
            context = ET.iterparse(f, events=('start', 'end'))
            context = iter(context)
            event, root = next(context)
            
            for event, elem in context:
                if event == 'end' and elem.tag == 'label':
                    try:
                        label_id = int(elem.find('id').text) if elem.find('id') is not None else None
                        if not label_id:
                            continue
                        
                        # Check if exists
                        exists = session.query(CachedLabel).filter_by(id=label_id).first()
                        if exists:
                            skipped += 1
                            elem.clear()
                            continue
                        
                        # Extract data
                        name = elem.find('name').text if elem.find('name') is not None else ''
                        contact_info = elem.find('contactinfo').text if elem.find('contactinfo') is not None else ''
                        profile = elem.find('profile').text if elem.find('profile') is not None else ''
                        
                        # URLs
                        urls = [url.text for url in elem.findall('.//url') if url.text]
                        
                        # Parent label
                        parent = elem.find('.//parentLabel')
                        parent_name = parent.get('name') if parent is not None else ''
                        
                        # Sublabels
                        sublabels = [sl.get('name') for sl in elem.findall('.//sublabels/label') if sl.get('name')]
                        
                        label = CachedLabel(
                            id=label_id,
                            name=name[:500] if name else '',
                            contact_info=contact_info,
                            profile=profile,
                            urls=','.join(urls),
                            parent_label=parent_name[:500] if parent_name else '',
                            sublabels=','.join(sublabels)
                        )
                        
                        batch.append(label)
                        count += 1
                        
                        # Batch insert
                        if len(batch) >= batch_size:
                            session.bulk_save_objects(batch)
                            session.commit()
                            batch = []
                            print(f"\r[LABELS] Imported: {count:,} (skipped: {skipped:,})", end='')
                        
                        if limit and count >= limit:
                            break
                    
                    except Exception as e:
                        print(f"\n[LABELS] Error parsing label: {e}")
                    
                    finally:
                        elem.clear()
                        root.clear()
        
        # Insert remaining
        if batch:
            session.bulk_save_objects(batch)
            session.commit()
        
        print(f"\n[LABELS] ✓ Import complete: {count:,} labels imported, {skipped:,} skipped")
        return count
    
    except Exception as e:
        print(f"\n[LABELS] Error: {e}")
        session.rollback()
        return 0
    finally:
        session.close()


def parse_masters_dump(filepath, db_manager, limit=None):
    """Parse masters dump and import to database"""
    print(f"[MASTERS] Parsing {filepath}...")
    
    session = db_manager.Session()
    count = 0
    skipped = 0
    batch = []
    batch_size = 5000
    
    # Désactiver autoflush pour plus de performance
    session.autoflush = False
    session.autocommit = False
    
    try:
        with gzip.open(filepath, 'rt', encoding='utf-8') as f:
            context = ET.iterparse(f, events=('start', 'end'))
            context = iter(context)
            event, root = next(context)
            
            for event, elem in context:
                if event == 'end' and elem.tag == 'master':
                    try:
                        master_id = int(elem.get('id')) if elem.get('id') else None
                        if not master_id:
                            continue
                        
                        # Check if exists
                        exists = session.query(CachedMaster).filter_by(id=master_id).first()
                        if exists:
                            skipped += 1
                            elem.clear()
                            continue
                        
                        # Extract data
                        title_elem = elem.find('title')
                        title = title_elem.text if title_elem is not None else ''
                        
                        # Artists
                        artists = []
                        for artist in elem.findall('.//artists/artist'):
                            name = artist.find('name')
                            if name is not None and name.text:
                                artists.append(name.text)
                        
                        # Main release
                        main_release_elem = elem.find('main_release')
                        main_release = int(main_release_elem.text) if main_release_elem is not None and main_release_elem.text else None
                        
                        # Year
                        year_elem = elem.find('year')
                        year = year_elem.text if year_elem is not None else ''
                        
                        # Genres
                        genres = [g.text for g in elem.findall('.//genres/genre') if g.text]
                        
                        # Styles
                        styles = [s.text for s in elem.findall('.//styles/style') if s.text]
                        
                        master = CachedMaster(
                            id=master_id,
                            title=title[:500] if title else '',
                            artists=', '.join(artists),
                            main_release=main_release,
                            year=year[:10] if year else '',
                            genres=', '.join(genres),
                            styles=', '.join(styles)
                        )
                        
                        batch.append(master)
                        count += 1
                        
                        # Batch insert
                        if len(batch) >= batch_size:
                            session.bulk_save_objects(batch)
                            session.commit()
                            batch = []
                            print(f"\r[MASTERS] Imported: {count:,} (skipped: {skipped:,})", end='')
                        
                        if limit and count >= limit:
                            break
                    
                    except Exception as e:
                        print(f"\n[MASTERS] Error parsing master: {e}")
                    
                    finally:
                        elem.clear()
                        root.clear()
        
        # Insert remaining
        if batch:
            session.bulk_save_objects(batch)
            session.commit()
        
        print(f"\n[MASTERS] ✓ Import complete: {count:,} masters imported, {skipped:,} skipped")
        return count
    
    except Exception as e:
        print(f"\n[MASTERS] Error: {e}")
        session.rollback()
        return 0
    finally:
        session.close()


def parse_releases_dump(filepath, db_manager, limit=None):
    """Parse releases dump and import to database"""
    print(f"[RELEASES] Parsing {filepath}...")
    
    session = db_manager.Session()
    count = 0
    skipped = 0
    batch = []
    batch_size = 5000  # Augmenté de 1000 à 5000
    
    # Désactiver autoflush et autocommit pour plus de performance
    session.autoflush = False
    session.autocommit = False
    
    try:
        with gzip.open(filepath, 'rt', encoding='utf-8') as f:
            context = ET.iterparse(f, events=('start', 'end'))
            context = iter(context)
            event, root = next(context)
            
            for event, elem in context:
                if event == 'end' and elem.tag == 'release':
                    try:
                        release_id = int(elem.get('id')) if elem.get('id') else None
                        if not release_id:
                            continue
                        
                        # Check if exists
                        exists = session.query(CachedRelease).filter_by(id=release_id).first()
                        if exists:
                            skipped += 1
                            elem.clear()
                            continue
                        
                        # Extract data
                        title_elem = elem.find('title')
                        title = title_elem.text if title_elem is not None else ''
                        
                        # Artists
                        artists = []
                        for artist in elem.findall('.//artists/artist'):
                            name = artist.find('name')
                            if name is not None and name.text:
                                artists.append(name.text)
                        
                        # Labels
                        labels = []
                        catnos = []
                        for label in elem.findall('.//labels/label'):
                            label_name = label.get('name')
                            catno = label.get('catno')
                            if label_name:
                                labels.append(label_name)
                            if catno:
                                catnos.append(catno)
                        
                        # Country
                        country_elem = elem.find('country')
                        country = country_elem.text if country_elem is not None else ''
                        
                        # Year
                        released_elem = elem.find('released')
                        year = released_elem.text[:4] if released_elem is not None and released_elem.text else ''
                        
                        # Genres
                        genres = [g.text for g in elem.findall('.//genres/genre') if g.text]
                        
                        # Styles
                        styles = [s.text for s in elem.findall('.//styles/style') if s.text]
                        
                        release = CachedRelease(
                            id=release_id,
                            title=title[:500] if title else '',
                            artists=', '.join(artists),
                            labels=', '.join(labels),
                            catno=', '.join(catnos),
                            country=country[:100] if country else '',
                            year=year[:10] if year else '',
                            genres=', '.join(genres),
                            styles=', '.join(styles),
                            url=f'https://www.discogs.com/release/{release_id}'
                        )
                        
                        batch.append(release)
                        count += 1
                        
                        # Batch insert
                        if len(batch) >= batch_size:
                            session.bulk_save_objects(batch)
                            session.commit()
                            batch = []
                            print(f"\r[RELEASES] Imported: {count:,} (skipped: {skipped:,})", end='')
                        
                        if limit and count >= limit:
                            break
                    
                    except Exception as e:
                        print(f"\n[RELEASES] Error parsing release: {e}")
                    
                    finally:
                        elem.clear()
                        root.clear()
        
        # Insert remaining
        if batch:
            session.bulk_save_objects(batch)
            session.commit()
        
        print(f"\n[RELEASES] ✓ Import complete: {count:,} releases imported, {skipped:,} skipped")
        return count
    
    except Exception as e:
        print(f"\n[RELEASES] Error: {e}")
        session.rollback()
        return 0
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description='Import all Discogs data dumps')
    parser.add_argument('--types', nargs='+', choices=['artists', 'labels', 'masters', 'releases'],
                        default=['artists', 'labels', 'masters', 'releases'],
                        help='Dump types to import (default: all)')
    parser.add_argument('--year-month', type=str,
                        help='Specific year to download (e.g., "2026")')
    parser.add_argument('--limit', type=int,
                        help='Limit number of records to import per dump (for testing)')
    parser.add_argument('--skip-download', action='store_true',
                        help='Skip download if files already exist')
    parser.add_argument('--skip-duplicates-check', action='store_true',
                        help='Skip checking for existing records (faster for first import)')
    parser.add_argument('--db-path', type=str, default='discogs_cache.db',
                        help='Path to SQLite database')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Discogs Data Dumps Import")
    print("=" * 60)
    print(f"Types to import: {', '.join(args.types)}")
    if args.limit:
        print(f"Limit per dump: {args.limit:,} records")
    print()
    
    # Initialize database
    db_manager = DatabaseManager(f'sqlite:///{args.db_path}')
    db_manager.init_db()
    
    # Import order: artists, labels, masters, releases
    parsers = {
        'artists': parse_artists_dump,
        'labels': parse_labels_dump,
        'masters': parse_masters_dump,
        'releases': parse_releases_dump
    }
    
    total_imported = 0
    
    for dump_type in args.types:
        print(f"\n{'=' * 60}")
        print(f"Processing {dump_type.upper()}")
        print('=' * 60)
        
        # Get latest dump URL
        url, filename = get_latest_dump_url(dump_type, args.year_month)
        
        if not url:
            print(f"[{dump_type.upper()}] ✗ No dump found, skipping")
            continue
        
        # Download dump
        if args.skip_download:
            filepath = os.path.join('data/dumps', filename)
            if not os.path.exists(filepath):
                print(f"[{dump_type.upper()}] File not found: {filepath}")
                filepath = download_dump(url, filename)
        else:
            filepath = download_dump(url, filename)
        
        if not filepath:
            print(f"[{dump_type.upper()}] ✗ Download failed, skipping")
            continue
        
        # Parse and import
        parser_func = parsers[dump_type]
        count = parser_func(filepath, db_manager, limit=args.limit)
        total_imported += count
    
    print(f"\n{'=' * 60}")
    print(f"✓ Import complete!")
    print(f"Total records imported: {total_imported:,}")
    print('=' * 60)


if __name__ == '__main__':
    main()
