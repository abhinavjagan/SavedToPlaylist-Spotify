"""
MusicBrainz Integration Module
Provides smart fusion of MusicBrainz and Spotify data

Features:
- Enhanced genre taxonomy (1000+ genres)
- Community tags (mood, style, themes)
- Artist relationships
- Community ratings
- Aggressive caching to respect rate limits (1 req/s)
"""

import time
import logging
import sqlite3
import hashlib
from typing import List, Dict, Any, Optional
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

# MusicBrainz API Configuration
MB_API_BASE = "https://musicbrainz.org/ws/2"
MB_USER_AGENT = "SavedToPlaylist-Spotify/2.0 (https://github.com/yourusername/SavedToPlaylist-Spotify)"
MB_RATE_LIMIT_DELAY = 1.0  # 1 second between requests


class MusicBrainzCache:
    """Persistent cache for MusicBrainz data to minimize API calls"""
    
    def __init__(self, db_path: str = 'musicbrainz_cache.db'):
        self.db_path = db_path
        self.init_db()
        self.last_request_time = 0
        
    def init_db(self):
        """Initialize the cache database"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Artist cache table
        c.execute('''
            CREATE TABLE IF NOT EXISTS mb_artists (
                spotify_id TEXT PRIMARY KEY,
                mb_id TEXT,
                artist_name TEXT,
                genres TEXT,
                tags TEXT,
                rating REAL,
                cached_at INTEGER,
                UNIQUE(spotify_id)
            )
        ''')
        
        # Genre mapping table
        c.execute('''
            CREATE TABLE IF NOT EXISTS mb_genres (
                genre_name TEXT PRIMARY KEY,
                usage_count INTEGER DEFAULT 0
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("MusicBrainz cache database initialized: %s", self.db_path)
    
    def get_artist_data(self, spotify_id: str, max_age_days: int = 30) -> Optional[Dict[str, Any]]:
        """Get cached artist data from MusicBrainz"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        max_age_seconds = max_age_days * 24 * 60 * 60
        min_timestamp = int(time.time()) - max_age_seconds
        
        c.execute('''
            SELECT mb_id, artist_name, genres, tags, rating, cached_at
            FROM mb_artists
            WHERE spotify_id = ? AND cached_at > ?
        ''', (spotify_id, min_timestamp))
        
        row = c.fetchone()
        conn.close()
        
        if row:
            mb_id, name, genres, tags, rating, cached_at = row
            return {
                'mb_id': mb_id,
                'name': name,
                'genres': genres.split(',') if genres else [],
                'tags': tags.split(',') if tags else [],
                'rating': float(rating) if rating is not None else 0.0,
                'cached_at': cached_at
            }
        return None
    
    def save_artist_data(self, spotify_id: str, mb_id: str, name: str, 
                        genres: List[str], tags: List[str], rating: float):
        """Save artist data to cache"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        genres_str = ','.join(genres) if genres else ''
        tags_str = ','.join(tags) if tags else ''
        
        c.execute('''
            INSERT OR REPLACE INTO mb_artists 
            (spotify_id, mb_id, artist_name, genres, tags, rating, cached_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (spotify_id, mb_id, name, genres_str, tags_str, rating, int(time.time())))
        
        conn.commit()
        conn.close()
        logger.debug("Cached MusicBrainz data for artist: %s", name)


class MusicBrainzEnricher:
    """Enrich Spotify data with MusicBrainz metadata"""
    
    def __init__(self, cache: MusicBrainzCache):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': MB_USER_AGENT,
            'Accept': 'application/json'
        })
        self.last_request_time = 0
        
    def _respect_rate_limit(self):
        """Ensure we don't exceed 1 request per second"""
        elapsed = time.time() - self.last_request_time
        if elapsed < MB_RATE_LIMIT_DELAY:
            sleep_time = MB_RATE_LIMIT_DELAY - elapsed
            logger.debug("Rate limiting: sleeping %.2fs", sleep_time)
            time.sleep(sleep_time)
        self.last_request_time = time.time()
    
    def _search_artist(self, artist_name: str, max_results: int = 1) -> Optional[str]:
        """Search for an artist by name and return their MBID"""
        try:
            self._respect_rate_limit()
            
            # Clean artist name for search
            clean_name = artist_name.strip().lower()
            
            url = f"{MB_API_BASE}/artist/"
            params = {
                'query': f'artist:"{clean_name}"',
                'limit': max_results,
                'fmt': 'json'
            }
            
            response = self.session.get(url, params=params, timeout=5)
            response.raise_for_status()
            
            data = response.json()
            artists = data.get('artists', [])
            
            if artists:
                # Return the best match (first result)
                best_match = artists[0]
                mb_id = best_match.get('id')
                logger.info("Found MusicBrainz ID for '%s': %s", artist_name, mb_id)
                return mb_id
            
            logger.warning("No MusicBrainz match found for artist: %s", artist_name)
            return None
            
        except Exception as e:
            logger.error("Error searching MusicBrainz for artist '%s': %s", artist_name, e)
            return None
    
    def _get_artist_details(self, mb_id: str) -> Dict[str, Any]:
        """Get detailed artist information from MusicBrainz"""
        try:
            self._respect_rate_limit()
            
            url = f"{MB_API_BASE}/artist/{mb_id}"
            params = {
                'inc': 'genres+tags+ratings',
                'fmt': 'json'
            }
            
            response = self.session.get(url, params=params, timeout=5)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract genres
            genres = []
            if 'genres' in data:
                genres = [g['name'] for g in data['genres'] if g.get('name')]
            
            # Extract tags (community contributed)
            tags = []
            if 'tags' in data:
                # Get top tags with significant vote count
                tags = [t['name'] for t in data['tags'] if t.get('count', 0) > 0][:10]
            
            # Extract rating
            rating = 0.0
            if 'rating' in data:
                rating_value = data['rating'].get('value')
                rating = float(rating_value) if rating_value is not None else 0.0
            
            logger.info("Retrieved details for MBID %s: %d genres, %d tags, rating %.1f", 
                       mb_id, len(genres), len(tags), rating)
            
            return {
                'genres': genres,
                'tags': tags,
                'rating': rating
            }
            
        except Exception as e:
            logger.error("Error fetching details for MBID %s: %s", mb_id, e)
            return {'genres': [], 'tags': [], 'rating': 0.0}
    
    def enrich_artist(self, spotify_id: str, artist_name: str) -> Dict[str, Any]:
        """
        Enrich Spotify artist with MusicBrainz data
        
        Returns:
            Dict with keys: mb_genres, mb_tags, mb_rating
        """
        # Check cache first
        cached_data = self.cache.get_artist_data(spotify_id)
        if cached_data:
            logger.debug("Using cached MusicBrainz data for: %s", artist_name)
            return {
                'mb_genres': cached_data['genres'],
                'mb_tags': cached_data['tags'],
                'mb_rating': cached_data['rating'],
                'from_cache': True
            }
        
        # Not in cache, fetch from MusicBrainz
        logger.info("Fetching fresh MusicBrainz data for: %s", artist_name)
        
        # Step 1: Find the artist's MBID
        mb_id = self._search_artist(artist_name)
        if not mb_id:
            # Save empty data to cache to avoid repeated lookups
            self.cache.save_artist_data(spotify_id, '', artist_name, [], [], 0.0)
            return {
                'mb_genres': [],
                'mb_tags': [],
                'mb_rating': 0.0,
                'from_cache': False
            }
        
        # Step 2: Get artist details
        details = self._get_artist_details(mb_id)
        
        # Step 3: Save to cache
        self.cache.save_artist_data(
            spotify_id, mb_id, artist_name,
            details['genres'], details['tags'], details['rating']
        )
        
        return {
            'mb_genres': details['genres'],
            'mb_tags': details['tags'],
            'mb_rating': details['rating'],
            'from_cache': False
        }
    
    def batch_enrich_artists(self, artists: List[Dict[str, str]], 
                            max_new_lookups: int = 5) -> Dict[str, Dict[str, Any]]:
        """
        Enrich multiple artists, but limit new API calls
        
        Args:
            artists: List of dicts with 'id' and 'name' keys
            max_new_lookups: Maximum number of new MusicBrainz API calls
        
        Returns:
            Dict mapping spotify_id to enrichment data
        """
        enriched = {}
        new_lookups = 0
        
        for artist in artists:
            spotify_id = artist['id']
            artist_name = artist['name']
            
            # Try cache first
            cached_data = self.cache.get_artist_data(spotify_id)
            if cached_data:
                enriched[spotify_id] = {
                    'mb_genres': cached_data['genres'],
                    'mb_tags': cached_data['tags'],
                    'mb_rating': cached_data['rating'],
                    'from_cache': True
                }
                continue
            
            # Only do new lookups if under limit
            if new_lookups < max_new_lookups:
                logger.info("Enriching artist %d/%d: %s", 
                           new_lookups + 1, max_new_lookups, artist_name)
                enrichment = self.enrich_artist(spotify_id, artist_name)
                enriched[spotify_id] = enrichment
                new_lookups += 1
            else:
                # No more new lookups allowed
                enriched[spotify_id] = {
                    'mb_genres': [],
                    'mb_tags': [],
                    'mb_rating': 0.0,
                    'from_cache': False,
                    'skipped': True
                }
        
        logger.info("Batch enrichment complete: %d artists, %d from cache, %d new lookups, %d skipped",
                   len(artists), 
                   sum(1 for e in enriched.values() if e.get('from_cache')),
                   new_lookups,
                   sum(1 for e in enriched.values() if e.get('skipped')))
        
        return enriched


# Global instances (lazy initialization)
_mb_cache = None
_mb_enricher = None


def get_enricher() -> MusicBrainzEnricher:
    """Get or create the global MusicBrainz enricher instance"""
    global _mb_cache, _mb_enricher
    
    if _mb_enricher is None:
        _mb_cache = MusicBrainzCache()
        _mb_enricher = MusicBrainzEnricher(_mb_cache)
        logger.info("MusicBrainz enricher initialized")
    
    return _mb_enricher

