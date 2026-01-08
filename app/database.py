"""
Database models and cache management for Discogs releases
"""
import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
import json

Base = declarative_base()


class CachedRelease(Base):
    """Cache table for Discogs releases"""
    __tablename__ = 'cached_releases'
    
    id = Column(Integer, primary_key=True)  # Discogs release ID
    title = Column(String(500))
    artists = Column(Text)
    labels = Column(Text)
    catno = Column(Text)
    country = Column(String(100))
    year = Column(String(10))
    genres = Column(Text)
    styles = Column(Text)
    price = Column(String(50))
    url = Column(Text)
    raw_data = Column(Text)  # Store full JSON for future use
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CachedArtist(Base):
    """Cache table for Discogs artists"""
    __tablename__ = 'cached_artists'
    
    id = Column(Integer, primary_key=True)  # Discogs artist ID
    name = Column(String(500))
    real_name = Column(String(500))
    profile = Column(Text)
    urls = Column(Text)  # JSON array
    name_variations = Column(Text)  # JSON array
    aliases = Column(Text)  # JSON array
    members = Column(Text)  # JSON array
    groups = Column(Text)  # JSON array
    raw_data = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CachedLabel(Base):
    """Cache table for Discogs labels"""
    __tablename__ = 'cached_labels'
    
    id = Column(Integer, primary_key=True)  # Discogs label ID
    name = Column(String(500))
    contact_info = Column(Text)
    profile = Column(Text)
    urls = Column(Text)  # JSON array
    parent_label = Column(String(500))
    sublabels = Column(Text)  # JSON array
    raw_data = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CachedMaster(Base):
    """Cache table for Discogs masters"""
    __tablename__ = 'cached_masters'
    
    id = Column(Integer, primary_key=True)  # Discogs master ID
    title = Column(String(500))
    artists = Column(Text)
    main_release = Column(Integer)
    year = Column(String(10))
    genres = Column(Text)
    styles = Column(Text)
    raw_data = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DatabaseManager:
    """Manage database connections and cache operations"""
    
    def __init__(self, database_url=None):
        if database_url is None:
            database_url = os.environ.get(
                'DATABASE_URL',
                'sqlite:///discogs_cache.db'  # SQLite par défaut
            )
        
        # Create engine with connection pooling
        self.engine = create_engine(
            database_url,
            poolclass=NullPool,  # Disable pooling for Flask
            echo=False
        )
        
        # Create session factory
        self.Session = sessionmaker(bind=self.engine)
    
    def init_db(self):
        """Initialize database tables"""
        Base.metadata.create_all(self.engine)
        print("[DB] Database tables created successfully")
    
    def get_cached_release(self, release_id):
        """
        Get a release from cache
        Returns dict with release data or None if not found or outdated
        
        Args:
            release_id: The Discogs release ID
        """
        session = self.Session()
        try:
            cached = session.query(CachedRelease).filter_by(id=release_id).first()
            
            if cached is None:
                return None
            
            # Check if cache is too old (optional: 30 days)
            cache_age = datetime.utcnow() - cached.updated_at
            if cache_age > timedelta(days=30):
                # Cache expired, delete it
                session.delete(cached)
                session.commit()
                return None
            
            # Return as dict
            return {
                'title': cached.title,
                'artists': cached.artists,
                'labels': cached.labels,
                'catno': cached.catno,
                'country': cached.country,
                'year': cached.year,
                'genres': cached.genres,
                'styles': cached.styles,
                'price': cached.price,
                'url': cached.url
            }
        except Exception as e:
            print(f"[DB] Error getting cached release {release_id}: {str(e)}")
            return None
        finally:
            session.close()
    
    def cache_release(self, release_id, release_data):
        """
        Store a release in cache
        release_data should be a dict with keys: title, artists, labels, catno, etc.
        """
        session = self.Session()
        try:
            # Check if already exists
            cached = session.query(CachedRelease).filter_by(id=release_id).first()
            
            if cached:
                # Update existing
                cached.title = release_data.get('title')
                cached.artists = release_data.get('artists')
                cached.labels = release_data.get('labels')
                cached.catno = release_data.get('catno')
                cached.country = release_data.get('country')
                cached.year = release_data.get('year')
                cached.genres = release_data.get('genres')
                cached.styles = release_data.get('styles')
                cached.price = release_data.get('price')
                cached.url = release_data.get('url')
                cached.updated_at = datetime.utcnow()
            else:
                # Create new
                cached = CachedRelease(
                    id=release_id,
                    title=release_data.get('title'),
                    artists=release_data.get('artists'),
                    labels=release_data.get('labels'),
                    catno=release_data.get('catno'),
                    country=release_data.get('country'),
                    year=release_data.get('year'),
                    genres=release_data.get('genres'),
                    styles=release_data.get('styles'),
                    price=release_data.get('price'),
                    url=release_data.get('url')
                )
                session.add(cached)
            
            session.commit()
        except Exception as e:
            print(f"[DB] Error caching release {release_id}: {str(e)}")
            session.rollback()
        finally:
            session.close()
    
    def get_cache_stats(self):
        """Get statistics about the cache"""
        session = self.Session()
        try:
            total = session.query(CachedRelease).count()
            
            # Count recent entries (last 7 days)
            week_ago = datetime.utcnow() - timedelta(days=7)
            recent = session.query(CachedRelease).filter(
                CachedRelease.updated_at >= week_ago
            ).count()
            
            return {
                'total_cached': total,
                'cached_last_week': recent
            }
        except Exception as e:
            print(f"[DB] Error getting cache stats: {str(e)}")
            return {'total_cached': 0, 'cached_last_week': 0}
        finally:
            session.close()
    
    def clear_old_cache(self, days=90):
        """Delete cache entries older than specified days"""
        session = self.Session()
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            deleted = session.query(CachedRelease).filter(
                CachedRelease.updated_at < cutoff_date
            ).delete()
            session.commit()
            print(f"[DB] Deleted {deleted} cache entries older than {days} days")
            return deleted
        except Exception as e:
            print(f"[DB] Error clearing old cache: {str(e)}")
            session.rollback()
            return 0
        finally:
            session.close()
