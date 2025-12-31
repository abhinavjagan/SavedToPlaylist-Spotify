"""
Spotify Recommendation System
Analyzes user's playlists and liked songs to generate personalized recommendations

IMPORTANT: Optimized for fast execution to avoid Gunicorn worker timeouts (45s limit).
All operations include aggressive timeout protection and early exit mechanisms.

ENHANCEMENT: Now includes MusicBrainz integration for enhanced genre taxonomy,
community tags, and artist ratings!
"""
import time
import logging
from collections import Counter
from typing import List, Dict, Any, Optional
import random
import spotipy
from spotipy.exceptions import SpotifyException

# Import MusicBrainz integration
try:
    from musicbrainz_integration import get_enricher
    MUSICBRAINZ_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("🎵 MusicBrainz integration available!")
except ImportError:
    MUSICBRAINZ_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("MusicBrainz integration not available (optional)")


class TimeoutException(Exception):
    """Exception raised when operation times out"""
    pass


class MusicTasteAnalyzer:
    """Analyzes user's music taste from playlists and liked songs
    
    Optimized for minimal API calls and fast execution to avoid worker timeouts.
    Default request timeout is 2 seconds per API call.
    """
    
    def __init__(self, sp: spotipy.Spotify, request_timeout: int = 2):
        self.sp = sp
        self.request_timeout = request_timeout
        # Set timeout on the Spotify client - CRITICAL for preventing hangs
        if hasattr(sp, '_session'):
            sp._session.timeout = request_timeout
        # Also set it directly on the client
        sp.requests_timeout = request_timeout
        logger.info("MusicTasteAnalyzer initialized with %ds request timeout", request_timeout)
        
    def get_user_playlists(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch all user's playlists"""
        playlists = []
        offset = 0
        max_retries = 2
        
        while True:
            for retry in range(max_retries):
                try:
                    response = self.sp.current_user_playlists(limit=min(limit - len(playlists), 50), offset=offset)
                    items = response.get('items', [])
                    if not items:
                        return playlists
                        
                    playlists.extend(items)
                    offset += len(items)
                    
                    if len(playlists) >= limit:
                        return playlists[:limit]
                    
                    break
                        
                except SpotifyException as e:
                    logger.warning("Spotify error fetching playlists (attempt %d/%d): %s", retry + 1, max_retries, e)
                    if retry == max_retries - 1:
                        return playlists
                except (ConnectionError, TimeoutError, OSError) as e:
                    logger.error("Network/timeout error fetching playlists: %s", e)
                    return playlists
                except Exception as e:
                    logger.error("Unexpected error fetching playlists: %s", e)
                    return playlists
            
            if not response.get('next'):
                break
                
        return playlists
    
    def get_playlist_tracks(self, playlist_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch tracks from a specific playlist"""
        tracks = []
        offset = 0
        max_retries = 2
        
        while len(tracks) < limit:
            for retry in range(max_retries):
                try:
                    response = self.sp.playlist_items(
                        playlist_id,
                        limit=min(limit - len(tracks), 100),
                        offset=offset,
                        fields='items(track(id,name,artists,album,popularity)),next'
                    )
                    
                    items = response.get('items', [])
                    if not items:
                        return tracks
                    
                    # Filter out None tracks and episodes
                    valid_tracks = [
                        item['track'] for item in items 
                        if item.get('track') and item['track'].get('type') == 'track' and item['track'].get('id')
                    ]
                    tracks.extend(valid_tracks)
                    offset += len(items)
                    
                    break
                        
                except SpotifyException as e:
                    logger.warning("Error fetching playlist tracks (attempt %d/%d): %s", retry + 1, max_retries, e)
                    if retry == max_retries - 1:
                        return tracks
                except (ConnectionError, TimeoutError, OSError) as e:
                    logger.error("Network/timeout error fetching playlist tracks: %s", e)
                    return tracks
                except Exception as e:
                    logger.error("Unexpected error fetching playlist tracks: %s", e)
                    return tracks
                    
            if not response.get('next'):
                break
                
        return tracks[:limit]
    
    def get_liked_songs(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Fetch user's liked songs - HEAVILY LIMITED for fast execution
        
        Default limit is 15 tracks (single API call) to prevent timeouts.
        NOW WITH RANDOMIZATION: Uses random offset to get different songs each time!
        """
        tracks = []
        
        try:
            # RANDOMIZE offset to get different songs each time (0-150 range)
            random_offset = random.randint(0, 150)  # Random starting point
            logger.info("Using RANDOM offset %d for liked songs (ensures variety!)", random_offset)
            
            # Single API call with random offset
            response = self.sp.current_user_saved_tracks(limit=min(limit, 50), offset=random_offset)
            items = response.get('items', [])
            
            if items:
                tracks = [item['track'] for item in items if item.get('track') and item['track'].get('id')]
                logger.info("Fetched %d liked songs from offset %d (requested %d)", 
                           len(tracks), random_offset, limit)
            else:
                logger.warning("No liked songs found at offset %d, trying offset 0", random_offset)
                # Fallback to beginning if random offset had no results
                response = self.sp.current_user_saved_tracks(limit=min(limit, 50), offset=0)
                items = response.get('items', [])
                if items:
                    tracks = [item['track'] for item in items if item.get('track') and item['track'].get('id')]
                    
        except (SpotifyException, ConnectionError, TimeoutError, OSError) as e:
            logger.error("Error fetching liked songs: %s - Returning empty list", e)
            return []
        except Exception as e:
            logger.error("Unexpected error fetching liked songs: %s - Returning empty list", e)
            return []
                    
        return tracks[:limit]
    
    def get_liked_song_ids_for_exclusion(self, limit: int = 200) -> List[str]:
        """Fetch user's liked song IDs for exclusion from recommendations
        
        Fetches up to 200 liked song IDs (4 API calls) to properly exclude them.
        This ensures recommendations are truly NEW songs.
        """
        track_ids = []
        offset = 0
        batch_size = 50
        
        try:
            while len(track_ids) < limit and offset < limit:
                response = self.sp.current_user_saved_tracks(
                    limit=batch_size, 
                    offset=offset
                    # Note: fields parameter not supported by spotipy properly
                )
                items = response.get('items', [])
                
                if not items:
                    break
                
                batch_ids = [
                    item['track']['id'] 
                    for item in items 
                    if item.get('track') and item['track'].get('id')
                ]
                track_ids.extend(batch_ids)
                offset += batch_size
                
                logger.info("Fetched %d/%d liked song IDs for exclusion...", len(track_ids), limit)
            
            logger.info("✅ Fetched %d liked song IDs for exclusion from recommendations", len(track_ids))
            return track_ids
                    
        except Exception as e:
            logger.warning("Could not fetch all liked song IDs: %s - Using partial list", e)
            return track_ids
    
    def extract_artist_ids(self, tracks: List[Dict[str, Any]]) -> List[str]:
        """Extract unique artist IDs from tracks"""
        artist_ids = set()
        
        for track in tracks:
            if track and track.get('artists'):
                for artist in track['artists']:
                    if artist.get('id'):
                        artist_ids.add(artist['id'])
                        
        return list(artist_ids)
    
    def get_artist_genres(self, artist_ids: List[str]) -> Dict[str, int]:
        """Fetch genres for artists and count frequency"""
        genre_counter = Counter()
        max_retries = 2
        
        # Process in batches of 50 (API limit)
        for i in range(0, len(artist_ids), 50):
            batch = artist_ids[i:i+50]
            
            for retry in range(max_retries):
                try:
                    artists = self.sp.artists(batch)
                    for artist in artists.get('artists', []):
                        if artist and artist.get('genres'):
                            genre_counter.update(artist['genres'])
                    
                    break
                            
                except SpotifyException as e:
                    logger.warning("Error fetching artist genres batch %d (attempt %d/%d): %s", i//50 + 1, retry + 1, max_retries, e)
                    # Continue to next batch even if this one fails
                except (ConnectionError, TimeoutError, OSError) as e:
                    logger.error("Network/timeout error fetching artist genres: %s", e)
                    break
                except Exception as e:
                    logger.error("Unexpected error fetching artist genres: %s", e)
                    break
                    
        return dict(genre_counter)
    
    def get_track_audio_features(self, track_ids: List[str]) -> Dict[str, float]:
        """Get average audio features for tracks"""
        features = {
            'danceability': [],
            'energy': [],
            'valence': [],
            'acousticness': [],
            'instrumentalness': [],
            'speechiness': [],
            'tempo': []
        }
        
        max_retries = 2
        
        # Process in batches of 100 (API limit)
        for i in range(0, len(track_ids), 100):
            batch = track_ids[i:i+100]
            
            for retry in range(max_retries):
                try:
                    audio_features = self.sp.audio_features(batch)
                    for feature_set in audio_features:
                        if feature_set:
                            for key in features.keys():
                                if feature_set.get(key) is not None:
                                    features[key].append(feature_set[key])
                    
                    break
                                    
                except SpotifyException as e:
                    logger.warning("Error fetching audio features batch %d (attempt %d/%d): %s", i//100 + 1, retry + 1, max_retries, e)
                except (ConnectionError, TimeoutError, OSError) as e:
                    logger.error("Network/timeout error fetching audio features: %s", e)
                    break
                except Exception as e:
                    logger.error("Unexpected error fetching audio features: %s", e)
                    break
        
        # Calculate averages
        avg_features = {}
        for key, values in features.items():
            if values:
                avg_features[key] = sum(values) / len(values)
                
        return avg_features
    
    def analyze_taste(self, include_playlists: bool = False, 
                     playlist_limit: int = 0,
                     tracks_per_playlist: int = 3,
                     liked_songs_limit: int = 15,
                     max_analysis_time: int = 20) -> Dict[str, Any]:
        """ULTRA-FAST music taste analysis with maximum timeout protection
        
        CRITICAL LIMITS (to prevent worker timeout):
        - Default: 15 liked songs only, NO playlists
        - Max analysis time: 20 seconds (25s buffer before 45s worker timeout)
        - Request timeout: 2 seconds per API call
        - Playlists: DISABLED by default (major timeout source)
        
        If analysis exceeds time budget, returns partial results immediately.
        """
        
        all_tracks = []
        start_time = time.time()
        
        # STEP 0.5: Fetch liked song IDs for exclusion (200 IDs, ~5 seconds)
        logger.info("[ANALYSIS START] Fetching liked song IDs for exclusion...")
        liked_song_ids_for_exclusion = []
        try:
            liked_song_ids_for_exclusion = self.get_liked_song_ids_for_exclusion(limit=200)
            elapsed = time.time() - start_time
            logger.info("[STEP 0.5/5] Fetched %d liked song IDs for exclusion in %.2fs", 
                       len(liked_song_ids_for_exclusion), elapsed)
        except Exception as e:
            logger.warning("[WARNING] Could not fetch all liked song IDs: %s - Continuing with partial list", e)
        
        # STEP 1: Fetch liked songs for analysis (MUST complete in < 3 seconds)
        logger.info("[STEP 1/5] Fetching max %d liked songs for analysis...", liked_songs_limit)
        try:
            liked_tracks = self.get_liked_songs(limit=liked_songs_limit)
            all_tracks.extend(liked_tracks)
            elapsed = time.time() - start_time
            logger.info("[STEP 1/5] Fetched %d liked songs in %.2fs", len(liked_tracks), elapsed)
            
            # Emergency exit if already too slow
            if elapsed > 10:
                logger.error("[TIMEOUT] Analysis took %.2fs (TOO SLOW), aborting", elapsed)
                raise TimeoutException(f"Analysis took {elapsed:.1f}s, exceeding safe limits")
                
        except TimeoutException:
            raise
        except Exception as e:
            logger.error("[ERROR] Failed to fetch liked songs: %s", e)
            raise TimeoutException(f"Failed to fetch liked songs: {e}")
        
        # STEP 2: Check if we should attempt playlists (RARELY RECOMMENDED)
        elapsed = time.time() - start_time
        if include_playlists and playlist_limit > 0:
            if elapsed > max_analysis_time * 0.3:  # Only 30% budget used
                logger.warning("[SKIP] Already used %.2fs (%.0f%%), SKIPPING playlists to prevent timeout", 
                             elapsed, (elapsed/max_analysis_time)*100)
                include_playlists = False
            else:
                logger.warning("[RISKY] Attempting playlist fetch (timeout risk HIGH)")
                # EXTREMELY LIMITED: Only 1 playlist, 3 tracks max
                try:
                    playlists = self.get_user_playlists(limit=1)
                    if playlists:
                        playlist_id = playlists[0].get('id')
                        if playlist_id:
                            tracks = self.get_playlist_tracks(playlist_id, limit=3)
                            all_tracks.extend(tracks)
                            logger.info("[STEP 2/5] Added %d playlist tracks", len(tracks))
                except Exception as e:
                    logger.warning("[ERROR] Playlist fetch failed (continuing): %s", e)
        
        # Validate we have tracks
        if not all_tracks:
            logger.error("[FAILED] No tracks found to analyze")
            return {
                'error': 'No tracks found to analyze. Please ensure you have liked songs in your Spotify library.',
                'track_count': 0
            }
        
        # Remove duplicates
        unique_tracks = {track['id']: track for track in all_tracks if track.get('id')}
        all_tracks = list(unique_tracks.values())
        logger.info("[STEP 3/5] Processing %d unique tracks...", len(all_tracks))
        
        # Extract artist IDs and count frequency (fast, no API calls)
        artist_counter = Counter()
        for track in all_tracks:
            if track.get('artists'):
                for artist in track['artists']:
                    if artist.get('id'):
                        artist_counter[artist['id']] += 1
        
        artist_ids = list(artist_counter.keys())
        top_artist_ids = [artist_id for artist_id, _ in artist_counter.most_common(10)]
        
        # STEP 4: Genre analysis (MUST complete in < 5 seconds total)
        elapsed = time.time() - start_time
        if elapsed > max_analysis_time * 0.5:  # 50% budget
            logger.warning("[SKIP] %.2fs elapsed, SKIPPING genre analysis to prevent timeout", elapsed)
            genres = {}
            top_genres = []
        else:
            # Only analyze top 10 artists (single API call = 2 seconds)
            top_artist_ids_for_genres = top_artist_ids[:10]
            logger.info("[STEP 4/5] Analyzing genres from %d artists...", len(top_artist_ids_for_genres))
            try:
                genres = self.get_artist_genres(top_artist_ids_for_genres)
                top_genres = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:10]
                logger.info("[STEP 4/5] Found %d genres in %.2fs", len(top_genres), time.time() - start_time - elapsed)
            except Exception as e:
                logger.warning("[ERROR] Genre analysis failed (continuing): %s", e)
                genres = {}
                top_genres = []
        
        # STEP 5: Audio features (MUST complete in < 8 seconds total)
        elapsed = time.time() - start_time
        if elapsed > max_analysis_time * 0.6:  # 60% budget
            logger.warning("[SKIP] %.2fs elapsed, SKIPPING audio features to prevent timeout", elapsed)
            avg_features = {}
        else:
            track_ids = [track['id'] for track in all_tracks if track.get('id')]
            
            # Limit to 15 tracks max (single API call = 2 seconds)
            if len(track_ids) > 15:
                random.seed(42)  # Reproducible sampling
                track_ids = random.sample(track_ids, 15)
            
            logger.info("[STEP 5/5] Analyzing audio features for %d tracks...", len(track_ids))
            try:
                avg_features = self.get_track_audio_features(track_ids)
                logger.info("[STEP 5/5] Analyzed audio features in %.2fs", time.time() - start_time - elapsed)
            except Exception as e:
                logger.warning("[ERROR] Audio feature analysis failed (continuing): %s", e)
                avg_features = {}
        
        # Final validation
        total_time = time.time() - start_time
        if total_time > max_analysis_time:
            logger.error("[WARNING] Analysis took %.2fs (exceeds %.2fs limit)", total_time, max_analysis_time)
        else:
            logger.info("[SUCCESS] Analysis completed in %.2fs (%.0f%% of budget)", 
                       total_time, (total_time/max_analysis_time)*100)
        
        # Use the comprehensive exclusion list (up to 200 songs)
        # If we couldn't fetch the exclusion list, fall back to the analyzed tracks
        if not liked_song_ids_for_exclusion:
            liked_song_ids_for_exclusion = [track['id'] for track in all_tracks if track.get('id')]
        
        logger.info("="*60)
        logger.info("ANALYSIS COMPLETE - EXCLUSION LIST: %d songs", len(liked_song_ids_for_exclusion))
        logger.info("="*60)
        
        return {
            'track_count': len(all_tracks),
            'unique_artists': len(artist_ids),
            'top_genres': top_genres,
            'top_artist_ids': top_artist_ids,
            'avg_audio_features': avg_features,
            'genre_seeds': [genre for genre, _ in top_genres[:5]] if top_genres else [],
            'liked_track_ids': liked_song_ids_for_exclusion,  # CRITICAL: Exclude these from recommendations!
            'analysis_time': round(total_time, 2)
        }


class RecommendationEngine:
    """Generates personalized recommendations based on music taste analysis
    
    Uses custom algorithm since Spotify recommendations API is deprecated.
    Finds recommendations by:
    1. Getting top tracks from user's favorite artists
    2. Getting tracks from related artists
    3. Scoring tracks based on genre match and popularity
    """
    
    # Mood to tag mappings for MusicBrainz filtering
    MOOD_TAG_MAPPING = {
        'chill': ['chill', 'relaxed', 'calm', 'mellow', 'ambient', 'peaceful', 'soft'],
        'energetic': ['energetic', 'upbeat', 'party', 'dance', 'hype', 'intense', 'fast'],
        'sad': ['melancholic', 'sad', 'depressing', 'emotional', 'dark', 'somber'],
        'happy': ['happy', 'cheerful', 'positive', 'uplifting', 'feel-good', 'joyful']
    }
    
    def __init__(self, sp: spotipy.Spotify):
        self.sp = sp
        
    def get_artist_top_tracks(self, artist_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get an artist's top tracks"""
        try:
            result = self.sp.artist_top_tracks(artist_id)
            tracks = result.get('tracks', [])[:limit]
            logger.info("Got %d top tracks for artist %s", len(tracks), artist_id)
            return tracks
        except Exception as e:
            logger.warning("Failed to get top tracks for artist %s: %s", artist_id, e)
            return []
    
    def get_related_artists(self, artist_id: str, limit: int = 5) -> List[str]:
        """Get related artist IDs (API is deprecated but may still work)"""
        try:
            result = self.sp.artist_related_artists(artist_id)
            artists = result.get('artists', [])[:limit]
            artist_ids = [a['id'] for a in artists if a.get('id')]
            logger.info("Got %d related artists for %s", len(artist_ids), artist_id)
            return artist_ids
        except Exception as e:
            logger.warning("Failed to get related artists for %s: %s (API deprecated)", artist_id, e)
            return []
    
    def discover_artists_by_genre(self, genres: List[str], exclude_artist_ids: List[str], 
                                   limit: int = 10) -> List[str]:
        """Discover new artists by searching for genres
        
        This replaces the deprecated related artists API
        """
        discovered_artists = []
        seen_ids = set(exclude_artist_ids)
        
        # Search for each genre
        for genre in genres[:3]:  # Limit to top 3 genres
            try:
                # Search for artists in this genre
                query = f'genre:"{genre}"'
                result = self.sp.search(q=query, type='artist', limit=10)
                
                artists = result.get('artists', {}).get('items', [])
                for artist in artists:
                    artist_id = artist.get('id')
                    # Only add if not already in user's favorites
                    if artist_id and artist_id not in seen_ids:
                        discovered_artists.append(artist_id)
                        seen_ids.add(artist_id)
                        logger.info("Discovered new artist via genre '%s': %s", 
                                   genre, artist.get('name'))
                        
                        if len(discovered_artists) >= limit:
                            return discovered_artists
                            
            except Exception as e:
                logger.warning("Failed to search genre '%s': %s", genre, e)
                continue
        
        logger.info("Discovered %d new artists via genre search", len(discovered_artists))
        return discovered_artists
    
    def get_user_top_artists(self, limit: int = 10, time_range: str = 'medium_term') -> List[str]:
        """Get user's top artists from Spotify's own calculations
        
        Args:
            limit: Number of top artists to return (max 50)
            time_range: 'short_term' (~4 weeks), 'medium_term' (~6 months), 'long_term' (~1 year)
        
        Returns:
            List of artist IDs
        """
        try:
            result = self.sp.current_user_top_artists(limit=min(limit, 50), time_range=time_range)
            artists = result.get('items', [])
            artist_ids = [a['id'] for a in artists if a.get('id')]
            logger.info("Got %d top artists from Spotify API (time_range=%s)", len(artist_ids), time_range)
            return artist_ids
        except Exception as e:
            logger.warning("Failed to get user top artists: %s", e)
            return []
    
    def get_user_top_tracks(self, limit: int = 20, time_range: str = 'medium_term') -> List[Dict[str, Any]]:
        """Get user's top tracks from Spotify's own calculations
        
        Args:
            limit: Number of top tracks to return (max 50)
            time_range: 'short_term' (~4 weeks), 'medium_term' (~6 months), 'long_term' (~1 year)
        
        Returns:
            List of track objects
        """
        try:
            result = self.sp.current_user_top_tracks(limit=min(limit, 50), time_range=time_range)
            tracks = result.get('items', [])
            logger.info("Got %d top tracks from Spotify API (time_range=%s)", len(tracks), time_range)
            return tracks
        except Exception as e:
            logger.warning("Failed to get user top tracks: %s", e)
            return []
    
    def get_artist_recent_albums(self, artist_id: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Get artist's recent albums and singles
        
        Args:
            artist_id: Spotify artist ID
            limit: Number of albums to return
        
        Returns:
            List of album objects
        """
        try:
            # Get albums and singles only (not compilations or appears_on)
            result = self.sp.artist_albums(artist_id, album_type='album,single', limit=limit)
            albums = result.get('items', [])[:limit]
            logger.info("Got %d recent albums/singles for artist %s", len(albums), artist_id)
            return albums
        except Exception as e:
            logger.warning("Failed to get albums for artist %s: %s", artist_id, e)
            return []
    
    def get_album_tracks(self, album_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get tracks from an album
        
        Args:
            album_id: Spotify album ID
            limit: Number of tracks to return
        
        Returns:
            List of track objects
        """
        try:
            result = self.sp.album_tracks(album_id, limit=limit)
            tracks = result.get('items', [])[:limit]
            logger.info("Got %d tracks from album %s", len(tracks), album_id)
            return tracks
        except Exception as e:
            logger.warning("Failed to get tracks from album %s: %s", album_id, e)
            return []
    
    def score_track(self, track: Dict[str, Any], target_genres: List[str], 
                    user_artist_ids: List[str], mb_enrichment: Optional[Dict[str, Dict]] = None,
                    seen_albums: Optional[set] = None, preferences: Optional[Dict[str, Any]] = None) -> float:
        """Score a track based on multiple factors (Spotify + MusicBrainz fusion)
        
        Returns a score between -20 to 155:
        BASE SCORING (0-75):
        - User's artist: +40 points (exact match)
        - Related artist: +25 points (from related artists)
        - Genre match: +25 points (up to 3 genres, Spotify)
        - Popularity: +10 points (scaled, favors popular but not too mainstream)
        
        MUSICBRAINZ BONUS (0-40):
        - Enhanced genre match: +20 points (detailed MusicBrainz genres)
        - Community tags match: +15 points (mood, style matching)
        - Community rating: +5 points (quality indicator)
        
        USER PREFERENCES (up to +40):
        - Era match: +30 points (matching decade) / -20 penalty (wrong decade)
        - Mood match: +10 points (if mood preference matches tags)
        - Discovery bonus: +10 points (based on slider 0-100%)
        
        PENALTIES:
        - Diversity: -15% (if same album repeated)
        - Era mismatch: -20 points (if era preference set and doesn't match)
        """
        score = 0.0
        preferences = preferences or {}
        
        # Factor 1: Artist relevance
        track_artists = track.get('artists', [])
        track_artist_ids = [a.get('id') for a in track_artists if a.get('id')]
        
        if any(aid in user_artist_ids for aid in track_artist_ids):
            # Exact match with user's favorite artists
            score += 40
        else:
            # Could be from related artists (partial credit)
            score += 25
        
        # Factor 2: Spotify Genre matching
        try:
            if track_artist_ids:
                artist_info = self.sp.artist(track_artist_ids[0])
                artist_genres = [g.lower() for g in artist_info.get('genres', [])]
                target_genres_lower = [g.lower() for g in target_genres]
                
                # Count genre matches (up to 3)
                genre_matches = sum(1 for g in artist_genres if g in target_genres_lower)
                if genre_matches > 0:
                    score += min(25, genre_matches * 8)
        except:
            pass
        
        # Factor 3: Popularity (sweet spot is 40-80 range)
        popularity = track.get('popularity', 0)
        if popularity >= 40 and popularity <= 80:
            # Optimal range: popular but not overly mainstream
            score += 10
        elif popularity > 80:
            # Very popular: good but slightly penalized
            score += 7
        elif popularity >= 20:
            # Moderate popularity
            score += 5
        else:
            # Low popularity: might be too obscure
            score += 2
        
        # MUSICBRAINZ ENHANCEMENT (if available)
        if MUSICBRAINZ_AVAILABLE and mb_enrichment and track_artist_ids:
            primary_artist_id = track_artist_ids[0]
            if primary_artist_id in mb_enrichment:
                mb_data = mb_enrichment[primary_artist_id]
                
                # Factor 4: MusicBrainz Enhanced Genre Match (+20 max)
                mb_genres = [g.lower() for g in mb_data.get('mb_genres', [])]
                if mb_genres:
                    # Match with target genres
                    mb_genre_matches = sum(1 for g in mb_genres if g in target_genres_lower)
                    if mb_genre_matches > 0:
                        bonus = min(20, mb_genre_matches * 5)
                        score += bonus
                        logger.debug("  MusicBrainz genre bonus: +%.1f (%d matches)", bonus, mb_genre_matches)
                
                # Factor 5: MusicBrainz Tag Match (+15 max)
                # Tags include mood, style, themes (e.g., "chill", "melancholic", "80s", etc.)
                mb_tags = [t.lower() for t in mb_data.get('mb_tags', [])]
                if mb_tags:
                    # Base tag bonus
                    tag_bonus = min(15, len(mb_tags[:5]) * 3)
                    score += tag_bonus
                    logger.debug("  MusicBrainz tag bonus: +%.1f (%d tags)", tag_bonus, len(mb_tags[:5]))
                    
                    # Factor 7: MOOD MATCH BONUS (+10 if mood preference matches)
                    mood_preference = preferences.get('mood')
                    if mood_preference and mood_preference in self.MOOD_TAG_MAPPING:
                        target_mood_tags = self.MOOD_TAG_MAPPING[mood_preference]
                        if any(tag in mb_tags for tag in target_mood_tags):
                            mood_bonus = 10
                            score += mood_bonus
                            logger.debug("  Mood match bonus: +%.1f (mood: %s)", mood_bonus, mood_preference)
                
                # Factor 6: MusicBrainz Community Rating (+5 max)
                mb_rating = mb_data.get('mb_rating', 0.0)
                if mb_rating and mb_rating > 0:
                    # MusicBrainz ratings are 0-100, scale to 0-5 bonus
                    rating_bonus = (mb_rating / 100) * 5
                    score += rating_bonus
                    logger.debug("  MusicBrainz rating bonus: +%.1f (rating: %.1f)", rating_bonus, mb_rating)
        
        # Factor 8: TIME-BASED SCORING (Era preference: +30 match, -20 mismatch)
        try:
            release_date = track.get('album', {}).get('release_date', '')
            if release_date and len(release_date) >= 4:
                from datetime import datetime
                year = int(release_date[:4])
                current_year = datetime.now().year
                
                # Apply era preference if specified (STRONG filtering)
                era_preference = preferences.get('era')
                if era_preference and era_preference != 'any':
                    era_matched = False
                    
                    if era_preference == '2020s' and year >= 2020:
                        score += 30  # Strong bonus for matching era
                        era_matched = True
                        logger.debug("  Era match bonus (2020s): +30")
                    elif era_preference == '2010s' and 2010 <= year < 2020:
                        score += 30
                        era_matched = True
                        logger.debug("  Era match bonus (2010s): +30")
                    elif era_preference == '2000s' and 2000 <= year < 2010:
                        score += 30
                        era_matched = True
                        logger.debug("  Era match bonus (2000s): +30")
                    elif era_preference == '90s' and 1990 <= year < 2000:
                        score += 30
                        era_matched = True
                        logger.debug("  Era match bonus (90s): +30")
                    elif era_preference == '80s' and year < 1990:
                        score += 30
                        era_matched = True
                        logger.debug("  Era match bonus (80s and earlier): +30")
                    
                    # Penalize tracks outside preferred era
                    if not era_matched:
                        score -= 20  # Significant penalty for wrong era
                        logger.debug("  Era mismatch penalty (%s vs %d): -20", era_preference, year)
                else:
                    # No preference: bonus for recent releases
                    if year >= current_year - 1:
                        score += 5  # New release bonus
                        logger.debug("  New release bonus: +5")
                    elif year >= current_year - 3:
                        score += 3  # Recent release bonus
                        logger.debug("  Recent release bonus: +3")
        except:
            pass
        
        # Factor 9: DIVERSITY PENALTY (avoid too many tracks from same album)
        if seen_albums is not None:
            album_id = track.get('album', {}).get('id')
            if album_id and album_id in seen_albums:
                # Penalize repeats from same album
                score *= 0.85  # 15% penalty
                logger.debug("  Diversity penalty: -15%% (album repeat)")
        
        # Factor 10: DISCOVERY SLIDER (if specified)
        discovery_level = preferences.get('discovery', 50)  # 0-100, default 50
        if discovery_level != 50:
            # Adjust score based on whether track is from user's artist or related
            is_users_artist = any(aid in user_artist_ids for aid in track_artist_ids)
            
            if discovery_level > 50:
                # User wants more discovery: boost related artists
                if not is_users_artist:
                    discovery_bonus = (discovery_level - 50) / 50 * 10  # Up to +10
                    score += discovery_bonus
                    logger.debug("  Discovery bonus: +%.1f", discovery_bonus)
            else:
                # User wants more familiar: boost own artists
                if is_users_artist:
                    familiar_bonus = (50 - discovery_level) / 50 * 10  # Up to +10
                    score += familiar_bonus
                    logger.debug("  Familiar bonus: +%.1f", familiar_bonus)
        
        # Factor 11: RANDOMIZATION (±5 points to ensure variety between runs)
        randomization_bonus = random.uniform(-5, 5)
        score += randomization_bonus
        logger.debug("  Randomization: %.1f (ensures different results each time)", randomization_bonus)
        
        return score
    
    def generate_recommendations(self, 
                                analysis: Dict[str, Any],
                                limit: int = 20,
                                include_audio_targets: bool = True,
                                preferences: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Generate track recommendations using custom algorithm
        
        Since Spotify recommendations API is deprecated, this uses:
        1. Artist's top tracks
        2. Related artists' top tracks  
        3. Custom scoring based on genre and popularity
        """
        
        logger.info("="*60)
        logger.info("CUSTOM RECOMMENDATION ALGORITHM")
        logger.info("="*60)
        logger.info("Limit: %d", limit)
        
        if analysis.get('error'):
            logger.error("Analysis has error: %s", analysis.get('error'))
            return []
        
        logger.info("Analysis data: track_count=%s, unique_artists=%s, top_genres=%s", 
                   analysis.get('track_count'), 
                   analysis.get('unique_artists'),
                   len(analysis.get('top_genres', [])))
        
        # Get artist IDs and genres from analysis
        analysis_artist_ids = analysis.get('top_artist_ids', [])[:5]  # Use top 5 artists from analysis
        user_genres = [g for g, _ in analysis.get('top_genres', [])][:5]
        
        # CRITICAL: Get user's already-liked track IDs to EXCLUDE from recommendations
        user_liked_track_ids = set(analysis.get('liked_track_ids', []))
        logger.info("Will EXCLUDE %d already-liked tracks from recommendations", len(user_liked_track_ids))
        
        logger.info("Analysis provided %d artists", len(analysis_artist_ids))
        logger.info("Target genres: %s", user_genres)
        
        # Step 1: Try to get user's ACTUAL top artists from Spotify API (more accurate!)
        logger.info("Step 1: Getting user's top artists from Spotify's algorithm...")
        top_artist_ids = []
        
        # Try to get user's top artists (this is better than analyzing liked songs)
        try:
            spotify_top_artists = self.get_user_top_artists(limit=10, time_range='medium_term')
            if spotify_top_artists:
                # RANDOMIZE which 5 artists we use from the top 10!
                if len(spotify_top_artists) > 5:
                    top_artist_ids = random.sample(spotify_top_artists, 5)
                    logger.info("✅ Using RANDOM 5 from top 10 Spotify artists (variety!)")
                else:
                    top_artist_ids = spotify_top_artists
                    logger.info("✅ Using Spotify's top artists: %d artists", len(top_artist_ids))
            else:
                logger.warning("Spotify top artists not available, falling back to analysis")
                # RANDOMIZE analysis artists too
                if len(analysis_artist_ids) > 5:
                    top_artist_ids = random.sample(analysis_artist_ids, 5)
                else:
                    top_artist_ids = analysis_artist_ids
        except Exception as e:
            logger.warning("Could not get Spotify top artists: %s - Using analysis artists", e)
            # RANDOMIZE analysis artists
            if len(analysis_artist_ids) > 5:
                top_artist_ids = random.sample(analysis_artist_ids, 5)
            else:
                top_artist_ids = analysis_artist_ids
        
        if not top_artist_ids:
            logger.error("No artists found")
            return []
        
        logger.info("Using %d artists for recommendations", len(top_artist_ids))
        
        # Step 2: Collect diverse tracks from multiple sources
        logger.info("Step 2: Collecting candidate tracks from multiple sources...")
        
        # Check discovery preference (0-100)
        discovery_level = preferences.get('discovery', 50) if preferences else 50
        logger.info("Discovery level: %d%% (0=Familiar, 100=Discovery)", discovery_level)
        
        candidate_tracks = []
        artist_track_ids = set()  # To avoid duplicates
        excluded_count = 0  # Count how many already-liked tracks we skip
        
        # Calculate how many tracks to get from each source based on discovery level
        if discovery_level < 30:
            # Low discovery: Mostly user's own artists
            familiar_tracks_per_artist = 8
            discovery_tracks_per_artist = 2
        elif discovery_level > 70:
            # High discovery: Mostly new artists
            familiar_tracks_per_artist = 3
            discovery_tracks_per_artist = 7
        else:
            # Balanced
            familiar_tracks_per_artist = 5
            discovery_tracks_per_artist = 5
        
        logger.info("  Familiar tracks/artist: %d, Discovery tracks/artist: %d", 
                   familiar_tracks_per_artist, discovery_tracks_per_artist)
        
        # PART A: Get tracks from USER'S FAVORITE ARTISTS (Familiar)
        for artist_id in top_artist_ids:
            tracks_from_this_artist = 0
            
            # Source 1: Top tracks (most familiar)
            top_tracks = self.get_artist_top_tracks(artist_id, limit=5)
            for track in top_tracks:
                if tracks_from_this_artist >= familiar_tracks_per_artist:
                    break
                track_id = track.get('id')
                # EXCLUDE already-liked songs
                if track_id and track_id in user_liked_track_ids:
                    excluded_count += 1
                    continue
                if track_id and track_id not in artist_track_ids:
                    candidate_tracks.append(track)
                    artist_track_ids.add(track_id)
                    tracks_from_this_artist += 1
            
            # Source 2: Recent albums (somewhat familiar)
            if tracks_from_this_artist < familiar_tracks_per_artist:
                recent_albums = self.get_artist_recent_albums(artist_id, limit=1)
                for album in recent_albums:
                    if tracks_from_this_artist >= familiar_tracks_per_artist:
                        break
                    album_id = album.get('id')
                    if album_id:
                        album_tracks = self.get_album_tracks(album_id, limit=3)
                        for track in album_tracks:
                            if tracks_from_this_artist >= familiar_tracks_per_artist:
                                break
                            track_id = track.get('id')
                            # EXCLUDE already-liked songs
                            if track_id and track_id in user_liked_track_ids:
                                excluded_count += 1
                                continue
                            if track_id and track_id not in artist_track_ids:
                                candidate_tracks.append(track)
                                artist_track_ids.add(track_id)
                                tracks_from_this_artist += 1
        
        logger.info("  Collected %d familiar tracks from user's artists", len(candidate_tracks))
        
        # PART B: DISCOVER NEW ARTISTS (Discovery)
        if discovery_level > 20:  # Only do discovery if slider > 20%
            logger.info("Step 3: Discovering new artists (discovery level: %d%%)", discovery_level)
            
            # Try related artists first (deprecated API, may fail)
            related_artist_ids = []
            for artist_id in top_artist_ids[:3]:  # Only try top 3 to save time
                related = self.get_related_artists(artist_id, limit=2)
                related_artist_ids.extend(related)
            
            # If related artists failed, use genre-based discovery
            if len(related_artist_ids) < 5:
                logger.info("  Related artists API limited, using genre-based discovery...")
                genre_discovered = self.discover_artists_by_genre(
                    user_genres, 
                    top_artist_ids,  # Exclude user's own artists
                    limit=10
                )
                related_artist_ids.extend(genre_discovered)
            
            # Remove duplicates and RANDOMIZE order
            related_artist_ids = list(set(related_artist_ids))
            random.shuffle(related_artist_ids)  # RANDOMIZE which discovery artists we use!
            num_discovery_artists = min(len(related_artist_ids), 5)
            logger.info("  Found %d new artists for discovery (randomized order)", num_discovery_artists)
            
            # Get tracks from discovered artists
            for artist_id in related_artist_ids[:num_discovery_artists]:
                tracks_from_artist = 0
                discovery_tracks = self.get_artist_top_tracks(artist_id, limit=5)
                
                for track in discovery_tracks:
                    if tracks_from_artist >= discovery_tracks_per_artist:
                        break
                    track_id = track.get('id')
                    # EXCLUDE already-liked songs
                    if track_id and track_id in user_liked_track_ids:
                        excluded_count += 1
                        continue
                    if track_id and track_id not in artist_track_ids:
                        candidate_tracks.append(track)
                        artist_track_ids.add(track_id)
                        tracks_from_artist += 1
            
            logger.info("  Added discovery tracks, total now: %d", len(candidate_tracks))
        
        logger.info("🎯 EXCLUDED %d already-liked tracks (NEW songs only!)", excluded_count)
        logger.info("Collected total %d candidate tracks (all NEW)", len(candidate_tracks))
        
        if not candidate_tracks:
            logger.error("No tracks found from artists")
            return []
        
        # Add randomization to ensure variety between requests
        random.shuffle(candidate_tracks)
        logger.info("Shuffled candidate tracks for variety")
        
        # Step 2.5: MUSICBRAINZ ENRICHMENT (Optional, smart caching)
        logger.info("Step 2.5: Enriching with MusicBrainz data...")
        mb_enrichment = {}
        
        if MUSICBRAINZ_AVAILABLE:
            try:
                enricher = get_enricher()
                
                # Prepare artist list for batch enrichment
                unique_artists = {}
                for track in candidate_tracks:
                    for artist in track.get('artists', []):
                        artist_id = artist.get('id')
                        artist_name = artist.get('name')
                        if artist_id and artist_id not in unique_artists:
                            unique_artists[artist_id] = artist_name
                
                artists_list = [
                    {'id': aid, 'name': name} 
                    for aid, name in unique_artists.items()
                ]
                
                logger.info("  Enriching %d unique artists (max 5 new API calls)...", len(artists_list))
                
                # Batch enrich (will use cache for most, only 5 new lookups max)
                mb_enrichment = enricher.batch_enrich_artists(artists_list, max_new_lookups=5)
                
                cached_count = sum(1 for e in mb_enrichment.values() if e.get('from_cache'))
                new_count = sum(1 for e in mb_enrichment.values() if not e.get('from_cache') and not e.get('skipped'))
                skipped_count = sum(1 for e in mb_enrichment.values() if e.get('skipped'))
                
                logger.info("  ✅ MusicBrainz enrichment: %d from cache, %d new, %d skipped",
                           cached_count, new_count, skipped_count)
                
                # Log some sample enrichments
                for artist_id, data in list(mb_enrichment.items())[:2]:
                    if data.get('mb_genres') or data.get('mb_tags'):
                        logger.info("  Sample: Artist %s - Genres: %s, Tags: %s", 
                                   artist_id[:8], 
                                   data.get('mb_genres', [])[:3],
                                   data.get('mb_tags', [])[:3])
                
            except Exception as e:
                logger.warning("MusicBrainz enrichment failed (continuing without): %s", e)
                mb_enrichment = {}
        else:
            logger.info("  Skipping MusicBrainz enrichment (not available)")
        
        # Step 3: Score and rank tracks (now with MusicBrainz data!)
        logger.info("Step 3: Scoring and ranking tracks...")
        if preferences:
            logger.info("  User preferences: mood=%s, era=%s, discovery=%s", 
                       preferences.get('mood', 'any'),
                       preferences.get('era', 'any'),
                       preferences.get('discovery', 50))
        
        scored_tracks = []
        seen_albums = set()
        
        for track in candidate_tracks:
            score = self.score_track(track, user_genres, top_artist_ids, mb_enrichment, 
                                    seen_albums, preferences)
            scored_tracks.append((score, track))
            
            # Track album for diversity scoring
            album_id = track.get('album', {}).get('id')
            if album_id:
                seen_albums.add(album_id)
        
        # Sort by score (highest first)
        scored_tracks.sort(key=lambda x: x[0], reverse=True)
        
        # Step 4: Return top N tracks
        recommendations = [track for score, track in scored_tracks[:limit]]
        
        logger.info("="*60)
        logger.info("RECOMMENDATION GENERATION COMPLETE")
        logger.info("="*60)
        logger.info("Returning %d recommendations", len(recommendations))
        if recommendations:
            logger.info("Top 3 recommendations (with scores):")
            for i, (score, track) in enumerate(scored_tracks[:3], 1):
                artist_name = track.get('artists', [{}])[0].get('name', 'Unknown')
                logger.info("  %d. %s - %s (score: %.1f, popularity: %d)", 
                           i, track.get('name'), artist_name, score, track.get('popularity', 0))
        
        return recommendations
    
    def create_recommendation_playlist(self,
                                      user_id: str,
                                      recommendations: List[Dict[str, Any]],
                                      playlist_name: Optional[str] = None,
                                      playlist_description: Optional[str] = None,
                                      public: bool = True) -> Dict[str, Any]:
        """Create a playlist with recommended tracks"""
        
        if not recommendations:
            return {'error': 'No recommendations to add to playlist'}
        
        # Generate playlist name if not provided
        if not playlist_name:
            from datetime import datetime
            playlist_name = f"Recommended Tracks - {datetime.now().strftime('%Y-%m-%d')}"
        
        if not playlist_description:
            playlist_description = "Personalized recommendations based on your music taste"
        
        try:
            # Create playlist
            playlist = self.sp.user_playlist_create(
                user_id,
                playlist_name,
                public=public,
                description=playlist_description
            )
            
            playlist_id = playlist['id']
            
            # Add tracks in batches of 100
            track_uris = [track['uri'] for track in recommendations if track.get('uri')]
            
            for i in range(0, len(track_uris), 100):
                batch = track_uris[i:i+100]
                self.sp.playlist_add_items(playlist_id, batch)
            
            return {
                'success': True,
                'playlist_id': playlist_id,
                'playlist_url': playlist.get('external_urls', {}).get('spotify'),
                'playlist_name': playlist_name,
                'track_count': len(track_uris)
            }
            
        except SpotifyException as e:
            logger.error("Error creating recommendation playlist: %s", e)
            error_msg = str(e)
            if hasattr(e, 'http_status'):
                logger.error("HTTP status code: %d", e.http_status)
                if e.http_status == 403:
                    error_msg = "Permission denied. Ensure your app has playlist-modify permissions."
            return {'error': error_msg}

