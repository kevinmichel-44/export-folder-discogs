#!/usr/bin/env python3
"""
Discogs Data Dump Importer

Downloads and imports monthly Discogs data dumps (releases, artists, labels, masters)
into the local database for faster lookups and offline access.

Usage:
    python scripts/import_discogs_dump.py [--type releases|artists|labels|masters]
    
Cron example (1st day of each month at 3am):
    0 3 1 * * cd /path/to/export-folder-discogs && . venv/bin/activate && python scripts/import_discogs_dump.py
"""

import os
import sys
import gzip
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

# Add app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from database import DatabaseManager, CachedRelease
from sqlalchemy import text


# Discogs data dump URLs
BASE_URL = "https://discogs-data-dumps.s3.us-west-2.amazonaws.com/data"


def get_latest_dump_url(dump_type='releases'):
    """Get URL of the latest dump file"""
    year = datetime.now().year
    month = datetime.now().month
    
    # Try current month, then previous months
    for m in range(month, 0, -1):
        month_str = f"{m:02d}"
        filename = f"discogs_{year}{month_str}01_{dump_type}.xml.gz"
        url = f"{BASE_URL}/{year}/{filename}"
        
        print(f"Checking {url}...")
        response = requests.head(url)
        if response.status_code == 200:
            size_mb = int(response.headers.get('content-length', 0)) / (1024 * 1024)
            print(f"✓ Found: {filename} ({size_mb:.1f} MB)")
            return url, filename
    
    print(f"❌ No dump found for {dump_type} in {year}")
    return None, None


def download_dump(url, filename, data_dir='data/dumps'):
    """Download dump file if not already present"""
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(data_dir, filename)
    
    if os.path.exists(filepath):
        print(f"✓ Already downloaded: {filepath}")
        return filepath
    
    print(f"Downloading {filename}...")
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    downloaded = 0
    
    with open(filepath, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    percent = (downloaded / total_size) * 100
                    print(f"\rProgress: {percent:.1f}% ({downloaded / (1024*1024):.1f} MB)", end='')
    
    print(f"\n✓ Downloaded: {filepath}")
    return filepath


def parse_releases_dump(filepath, db_manager, limit=None):
    """Parse releases XML dump and import to database"""
    print(f"\nParsing releases from {filepath}...")
    
    count = 0
    imported = 0
    skipped = 0
    
    with gzip.open(filepath, 'rt', encoding='utf-8') as f:
        # Use iterparse for memory efficiency
        context = ET.iterparse(f, events=('start', 'end'))
        context = iter(context)
        event, root = next(context)
        
        for event, elem in context:
            if event == 'end' and elem.tag == 'release':
                count += 1
                
                if limit and count > limit:
                    break
                
                try:
                    release_id = int(elem.get('id'))
                    
                    # Check if already exists
                    session = db_manager.Session()
                    existing = session.query(CachedRelease).filter_by(id=release_id).first()
                    
                    if existing:
                        skipped += 1
                        session.close()
                    else:
                        # Extract data
                        title = elem.find('title')
                        title = title.text if title is not None else 'Unknown'
                        
                        artists = []
                        artists_elem = elem.find('artists')
                        if artists_elem is not None:
                            for artist in artists_elem.findall('artist'):
                                name = artist.find('name')
                                if name is not None:
                                    artists.append(name.text)
                        
                        labels = []
                        catno = 'Unknown'
                        labels_elem = elem.find('labels')
                        if labels_elem is not None:
                            for label in labels_elem.findall('label'):
                                label_name = label.get('name', '')
                                if label_name:
                                    labels.append(label_name)
                                if not catno or catno == 'Unknown':
                                    catno = label.get('catno', 'Unknown')
                        
                        country = elem.find('country')
                        country = country.text if country is not None else 'Unknown'
                        
                        released = elem.find('released')
                        year = released.text if released is not None else 'Unknown'
                        
                        genres = []
                        genres_elem = elem.find('genres')
                        if genres_elem is not None:
                            genres = [g.text for g in genres_elem.findall('genre') if g.text]
                        
                        styles = []
                        styles_elem = elem.find('styles')
                        if styles_elem is not None:
                            styles = [s.text for s in styles_elem.findall('style') if s.text]
                        
                        # Create cache entry
                        cached_release = CachedRelease(
                            id=release_id,
                            title=title,
                            artists=', '.join(artists),
                            labels=', '.join(labels),
                            catno=catno,
                            country=country,
                            year=year,
                            genres=', '.join(genres),
                            styles=', '.join(styles),
                            url=f"https://www.discogs.com/release/{release_id}"
                        )
                        
                        session.add(cached_release)
                        session.commit()
                        session.close()
                        
                        imported += 1
                    
                    if count % 10000 == 0:
                        print(f"Processed {count:,} releases (imported: {imported:,}, skipped: {skipped:,})")
                
                except Exception as e:
                    print(f"Error processing release {elem.get('id')}: {e}")
                
                # Clear element to free memory
                elem.clear()
                root.clear()
    
    print(f"\n✓ Import complete!")
    print(f"  Total processed: {count:,}")
    print(f"  Imported: {imported:,}")
    print(f"  Skipped (already in DB): {skipped:,}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Import Discogs data dumps')
    parser.add_argument('--type', default='releases', choices=['releases', 'artists', 'labels', 'masters'],
                       help='Type of dump to import')
    parser.add_argument('--limit', type=int, help='Limit number of records (for testing)')
    parser.add_argument('--skip-download', action='store_true', help='Skip download if file exists')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("  DISCOGS DATA DUMP IMPORTER")
    print("=" * 70 + "\n")
    
    # Get latest dump URL
    url, filename = get_latest_dump_url(args.type)
    if not url:
        return 1
    
    # Download dump
    if not args.skip_download:
        filepath = download_dump(url, filename)
    else:
        filepath = os.path.join('data/dumps', filename)
        if not os.path.exists(filepath):
            print(f"❌ File not found: {filepath}")
            return 1
    
    # Initialize database
    db_manager = DatabaseManager()
    
    # Import data
    if args.type == 'releases':
        parse_releases_dump(filepath, db_manager, limit=args.limit)
    else:
        print(f"⚠️  Import for {args.type} not yet implemented")
        print(f"   (currently only 'releases' is supported)")
    
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
