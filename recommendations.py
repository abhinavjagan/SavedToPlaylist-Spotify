"""
Spotify Recommendation System
Analyzes user's playlists and liked songs to generate personalized recommendations
"""
import time
import logging
from collections import Counter
from typing import List, Dict, Any, Set, Tuple
import spotipy
from spotipy.exceptions import SpotifyException

logger = logging.getLogger(__name__)


class MusicTasteAnalyzer:
    """Analyzes user's music taste from playlists and liked songs"""
    
    def __init__(self, sp: spotipy.Spotify, request_timeout: int = 10):
        self.sp = sp
        self.request_timeout = request_timeout
        # Set timeout on the underlying session
        if hasattr(sp, '_session'):
            sp._session.timeout = request_timeout
        
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
                    logger.warning(f"Spotify error fetching playlists (attempt {retry + 1}/{max_retries}): {e}")
                    if retry == max_retries - 1:
                        return playlists
                    time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Unexpected error fetching playlists: {e}")
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
                    logger.warning(f"Error fetching playlist tracks (attempt {retry + 1}/{max_retries}): {e}")
                    if retry == max_retries - 1:
                        return tracks
                    time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Unexpected error fetching playlist tracks: {e}")
                    return tracks
                    
            if not response.get('next'):
                break
                
        return tracks[:limit]
    
    def get_liked_songs(self, limit: int = 500) -> List[Dict[str, Any]]:
        """Fetch user's liked songs"""
        tracks = []
        offset = 0
        max_retries = 2
        
        while len(tracks) < limit:
            for retry in range(max_retries):
                try:
                    response = self.sp.current_user_saved_tracks(
                        limit=min(limit - len(tracks), 50),
                        offset=offset
                    )
                    
                    items = response.get('items', [])
                    if not items:
                        return tracks
                    
                    tracks.extend([item['track'] for item in items if item.get('track') and item['track'].get('id')])
                    offset += len(items)
                    
                    # Small delay
                    time.sleep(0.05)
                    break
                        
                except SpotifyException as e:
                    logger.warning(f"Error fetching liked songs (attempt {retry + 1}/{max_retries}): {e}")
                    if retry == max_retries - 1:
                        return tracks
                    time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Unexpected error fetching liked songs: {e}")
                    return tracks
                    
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
                    logger.warning(f"Error fetching artist genres batch {i//50 + 1} (attempt {retry + 1}/{max_retries}): {e}")
                    if retry < max_retries - 1:
                        time.sleep(0.5)
                    # Continue to next batch even if this one fails
                except Exception as e:
                    logger.error(f"Unexpected error fetching artist genres: {e}")
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
                    logger.warning(f"Error fetching audio features batch {i//100 + 1} (attempt {retry + 1}/{max_retries}): {e}")
                    if retry < max_retries - 1:
                        time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Unexpected error fetching audio features: {e}")
                    break
        
        # Calculate averages
        avg_features = {}
        for key, values in features.items():
            if values:
                avg_features[key] = sum(values) / len(values)
                
        return avg_features
    
    def analyze_taste(self, include_playlists: bool = True, 
                     playlist_limit: int = 2,
                     tracks_per_playlist: int = 15) -> Dict[str, Any]:
        """Comprehensive analysis of user's music taste"""
        
        all_tracks = []
        start_time = time.time()
        
        # Get liked songs (heavily reduced for faster processing)
        logger.info("Fetching liked songs...")
        liked_tracks = self.get_liked_songs(limit=30)  # Reduced from 50 to 30
        all_tracks.extend(liked_tracks)
        logger.info(f"Fetched {len(liked_tracks)} liked songs in {time.time() - start_time:.2f}s")
        
        # Get playlist tracks
        if include_playlists:
            playlist_start = time.time()
            logger.info("Fetching playlists...")
            playlists = self.get_user_playlists(limit=playlist_limit)
            logger.info(f"Fetched {len(playlists)} playlists in {time.time() - playlist_start:.2f}s")
            
            for idx, playlist in enumerate(playlists[:playlist_limit]):
                # Check if we're approaching timeout (stop at 20 seconds to be safe)
                if time.time() - start_time > 20:
                    logger.warning(f"Approaching timeout, stopping playlist analysis at {idx}/{playlist_limit}")
                    break
                    
                playlist_id = playlist.get('id')
                if playlist_id:
                    logger.info(f"Analyzing playlist {idx + 1}/{min(len(playlists), playlist_limit)}: {playlist.get('name')}")
                    try:
                        track_start = time.time()
                        tracks = self.get_playlist_tracks(playlist_id, limit=tracks_per_playlist)
                        all_tracks.extend(tracks)
                        logger.info(f"Fetched {len(tracks)} tracks in {time.time() - track_start:.2f}s")
                    except Exception as e:
                        logger.error(f"Error processing playlist {playlist.get('name')}: {e}")
                        continue
        
        if not all_tracks:
            return {
                'error': 'No tracks found to analyze',
                'track_count': 0
            }
        
        # Remove duplicates
        unique_tracks = {track['id']: track for track in all_tracks if track.get('id')}
        all_tracks = list(unique_tracks.values())
        
        logger.info(f"Analyzing {len(all_tracks)} unique tracks...")
        
        # Extract artist IDs and count frequency
        artist_counter = Counter()
        for track in all_tracks:
            if track.get('artists'):
                for artist in track['artists']:
                    if artist.get('id'):
                        artist_counter[artist['id']] += 1
        
        # Only analyze top 30 artists for genres (reduced from 50 for performance)
        top_artist_ids_for_genres = [artist_id for artist_id, _ in artist_counter.most_common(30)]
        artist_ids = list(artist_counter.keys())
        
        # Get genre distribution from top artists only
        # Check timeout
        if time.time() - start_time > 25:
            logger.warning("Approaching timeout, skipping genre analysis")
            genres = {}
            top_genres = []
        else:
            logger.info(f"Analyzing genres from top {len(top_artist_ids_for_genres)} artists...")
            genre_start = time.time()
            genres = self.get_artist_genres(top_artist_ids_for_genres)
            top_genres = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:10]
            logger.info(f"Analyzed genres in {time.time() - genre_start:.2f}s")
        
        # Get audio features (sample if too many tracks)
        # Check timeout before expensive operations
        if time.time() - start_time > 25:
            logger.warning("Approaching timeout, skipping audio feature analysis")
            avg_features = {}
        else:
            logger.info("Analyzing audio features...")
            track_ids = [track['id'] for track in all_tracks if track.get('id')]
            
            # Limit audio feature analysis to 100 tracks max for performance (reduced from 200)
            if len(track_ids) > 100:
                import random
                track_ids = random.sample(track_ids, 100)
                logger.info(f"Sampled {len(track_ids)} tracks for audio feature analysis")
            
            feature_start = time.time()
            avg_features = self.get_track_audio_features(track_ids)
            logger.info(f"Analyzed audio features in {time.time() - feature_start:.2f}s")
        
        # Get top artists (already counted above)
        top_artist_ids = [artist_id for artist_id, _ in artist_counter.most_common(10)]
        
        total_time = time.time() - start_time
        logger.info(f"Total taste analysis completed in {total_time:.2f}s")
        
        return {
            'track_count': len(all_tracks),
            'unique_artists': len(artist_ids),
            'top_genres': top_genres,
            'top_artist_ids': top_artist_ids,
            'avg_audio_features': avg_features,
            'genre_seeds': [genre for genre, _ in top_genres[:5]],
            'analysis_time': round(total_time, 2)
        }


class RecommendationEngine:
    """Generates personalized recommendations based on music taste analysis"""
    
    def __init__(self, sp: spotipy.Spotify):
        self.sp = sp
        
    def get_available_genres(self) -> List[str]:
        """Get list of available genre seeds"""
        try:
            return self.sp.recommendation_genre_seeds().get('genres', [])
        except SpotifyException as e:
            logger.error(f"Error fetching genre seeds: {e}")
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
        seed_artists = analysis.get('top_artist_ids', [])[:2]
        seed_genres = [
            genre for genre in analysis.get('genre_seeds', [])[:5]
            if genre in available_genres
        ]
        
        # Ensure total seeds don't exceed 5 (Spotify API limit)
        total_seeds = len(seed_artists) + len(seed_genres)
        if total_seeds > 5:
            # Prioritize artists, then trim genres
            max_genres = 5 - len(seed_artists)
            seed_genres = seed_genres[:max_genres]
        
        # Ensure we have at least one seed
        if not seed_artists and not seed_genres:
            logger.warning("No valid seeds found for recommendations")
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
            logger.info(f"Requesting recommendations with params: {params}")
            response = self.sp.recommendations(**params)
            recommendations = response.get('tracks', [])
            
        except SpotifyException as e:
            logger.error(f"Error getting recommendations: {e}")
            
        return recommendations
    
    def create_recommendation_playlist(self,
                                      user_id: str,
                                      recommendations: List[Dict[str, Any]],
                                      playlist_name: str = None,
                                      playlist_description: str = None,
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
            logger.error(f"Error creating recommendation playlist: {e}")
            return {'error': str(e)}
