"""
Spotify Recommendation System
Analyzes user's playlists and liked songs to generate personalized recommendations

IMPORTANT: Optimized for fast execution to avoid Gunicorn worker timeouts (45s limit).
All operations include aggressive timeout protection and early exit mechanisms.
"""
import time
import logging
from collections import Counter
from typing import List, Dict, Any, Optional
import random
import spotipy
from spotipy.exceptions import SpotifyException

logger = logging.getLogger(__name__)


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
                    
                    # Small delay to avoid rate limiting
                    time.sleep(0.05)
                    break
                        
                except SpotifyException as e:
                    logger.warning("Spotify error fetching playlists (attempt %d/%d): %s", retry + 1, max_retries, e)
                    if retry == max_retries - 1:
                        return playlists
                    time.sleep(0.3)
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
                    
                    # Small delay
                    time.sleep(0.05)
                    break
                        
                except SpotifyException as e:
                    logger.warning("Error fetching playlist tracks (attempt %d/%d): %s", retry + 1, max_retries, e)
                    if retry == max_retries - 1:
                        return tracks
                    time.sleep(0.3)
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
        No retries, no pagination to keep execution under 2 seconds.
        """
        tracks = []
        
        try:
            # Single API call, no retries, strict timeout
            response = self.sp.current_user_saved_tracks(limit=min(limit, 50), offset=0)
            items = response.get('items', [])
            
            if items:
                tracks = [item['track'] for item in items if item.get('track') and item['track'].get('id')]
                logger.info("Fetched %d liked songs (requested %d)", len(tracks), limit)
            else:
                logger.warning("No liked songs found")
                    
        except (SpotifyException, ConnectionError, TimeoutError, OSError) as e:
            logger.error("Error fetching liked songs: %s - Returning empty list", e)
            return []
        except Exception as e:
            logger.error("Unexpected error fetching liked songs: %s - Returning empty list", e)
            return []
                    
        return tracks[:limit]
    
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
                    
                    # Small delay between batches
                    time.sleep(0.05)
                    break
                            
                except SpotifyException as e:
                    logger.warning("Error fetching artist genres batch %d (attempt %d/%d): %s", i//50 + 1, retry + 1, max_retries, e)
                    if retry < max_retries - 1:
                        time.sleep(0.3)
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
                    
                    # Small delay between batches
                    time.sleep(0.05)
                    break
                                    
                except SpotifyException as e:
                    logger.warning("Error fetching audio features batch %d (attempt %d/%d): %s", i//100 + 1, retry + 1, max_retries, e)
                    if retry < max_retries - 1:
                        time.sleep(0.3)
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
        
        # STEP 1: Fetch liked songs (MUST complete in < 3 seconds)
        logger.info("[ANALYSIS START] Fetching max %d liked songs...", liked_songs_limit)
        try:
            liked_tracks = self.get_liked_songs(limit=liked_songs_limit)
            all_tracks.extend(liked_tracks)
            elapsed = time.time() - start_time
            logger.info("[STEP 1/4] Fetched %d liked songs in %.2fs", len(liked_tracks), elapsed)
            
            # Emergency exit if already too slow
            if elapsed > 5:
                logger.error("[TIMEOUT] Liked songs took %.2fs (TOO SLOW), aborting analysis", elapsed)
                raise TimeoutException(f"Liked songs fetch took {elapsed:.1f}s, exceeding safe limits")
                
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
                            logger.info("[STEP 2/4] Added %d playlist tracks", len(tracks))
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
        logger.info("[STEP 3/4] Processing %d unique tracks...", len(all_tracks))
        
        # Extract artist IDs and count frequency (fast, no API calls)
        artist_counter = Counter()
        for track in all_tracks:
            if track.get('artists'):
                for artist in track['artists']:
                    if artist.get('id'):
                        artist_counter[artist['id']] += 1
        
        artist_ids = list(artist_counter.keys())
        top_artist_ids = [artist_id for artist_id, _ in artist_counter.most_common(10)]
        
        # STEP 3: Genre analysis (MUST complete in < 5 seconds total)
        elapsed = time.time() - start_time
        if elapsed > max_analysis_time * 0.5:  # 50% budget
            logger.warning("[SKIP] %.2fs elapsed, SKIPPING genre analysis to prevent timeout", elapsed)
            genres = {}
            top_genres = []
        else:
            # Only analyze top 10 artists (single API call = 2 seconds)
            top_artist_ids_for_genres = top_artist_ids[:10]
            logger.info("[STEP 3/4] Analyzing genres from %d artists...", len(top_artist_ids_for_genres))
            try:
                genres = self.get_artist_genres(top_artist_ids_for_genres)
                top_genres = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:10]
                logger.info("[STEP 3/4] Found %d genres in %.2fs", len(top_genres), time.time() - start_time - elapsed)
            except Exception as e:
                logger.warning("[ERROR] Genre analysis failed (continuing): %s", e)
                genres = {}
                top_genres = []
        
        # STEP 4: Audio features (MUST complete in < 8 seconds total)
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
            
            logger.info("[STEP 4/4] Analyzing audio features for %d tracks...", len(track_ids))
            try:
                avg_features = self.get_track_audio_features(track_ids)
                logger.info("[STEP 4/4] Analyzed audio features in %.2fs", time.time() - start_time - elapsed)
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
        
        return {
            'track_count': len(all_tracks),
            'unique_artists': len(artist_ids),
            'top_genres': top_genres,
            'top_artist_ids': top_artist_ids,
            'avg_audio_features': avg_features,
            'genre_seeds': [genre for genre, _ in top_genres[:5]] if top_genres else [],
            'analysis_time': round(total_time, 2)
        }


class RecommendationEngine:
    """Generates personalized recommendations based on music taste analysis"""
    
    def __init__(self, sp: spotipy.Spotify):
        self.sp = sp
        
    def get_available_genres(self) -> List[str]:
        """Get list of available genre seeds with retry logic"""
        max_retries = 3
        for retry in range(max_retries):
            try:
                return self.sp.recommendation_genre_seeds().get('genres', [])
            except SpotifyException as e:
                logger.warning("Error fetching genre seeds (attempt %d/%d): %s", retry + 1, max_retries, e)
                if retry < max_retries - 1:
                    time.sleep(0.5 * (retry + 1))  # Exponential backoff
        
        # If all retries failed
        logger.error("Failed to fetch genre seeds after %d attempts", max_retries)
        return []
    
    def generate_recommendations(self, 
                                analysis: Dict[str, Any],
                                limit: int = 20,
                                include_audio_targets: bool = True) -> List[Dict[str, Any]]:
        """Generate track recommendations based on taste analysis"""
        
        if analysis.get('error'):
            return []
        
        recommendations = []
        available_genres = self.get_available_genres()
        
        # Prepare seeds - max 5 total (Spotify API constraint)
        seed_artists = analysis.get('top_artist_ids', [])[:2]  # Max 2 artists
        
        # Filter and limit genres
        candidate_genres = [
            genre for genre in analysis.get('genre_seeds', [])
            if genre in available_genres
        ]
        
        # Calculate max genres we can use (total seeds must be ≤ 5)
        max_genres = min(5 - len(seed_artists), len(candidate_genres))
        seed_genres = candidate_genres[:max_genres]
        
        # Ensure we have at least one seed
        if not seed_artists and not seed_genres:
            logger.error("No valid seeds found for recommendations. Artists: %d, Valid genres: %d/%d", 
                        len(analysis.get('top_artist_ids', [])), 
                        len(candidate_genres),
                        len(analysis.get('genre_seeds', [])))
            # Try fallback: use top tracks as seed if available
            if analysis.get('track_count', 0) > 0:
                logger.info("Attempting to use top tracks as fallback seed")
                # This would require track IDs, which we don't have in the analysis
                # For now, return empty with clear error
            return []
        
        # Prepare parameters
        params = {
            'limit': min(limit, 100),
            'seed_artists': ','.join(seed_artists) if seed_artists else None,
            'seed_genres': ','.join(seed_genres) if seed_genres else None,
        }
        
        # Add audio feature targets
        if include_audio_targets and analysis.get('avg_audio_features'):
            features = analysis['avg_audio_features']
            
            if 'energy' in features:
                params['target_energy'] = round(features['energy'], 2)
            if 'danceability' in features:
                params['target_danceability'] = round(features['danceability'], 2)
            if 'valence' in features:
                params['target_valence'] = round(features['valence'], 2)
        
        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}
        
        try:
            logger.info("Requesting recommendations with params: %s", params)
            response = self.sp.recommendations(**params)
            recommendations = response.get('tracks', [])
            logger.info("Received %d recommendations from Spotify", len(recommendations))
            
        except SpotifyException as e:
            logger.error("Error getting recommendations: %s", e)
            if hasattr(e, 'http_status'):
                logger.error("HTTP status code: %d", e.http_status)
            
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
