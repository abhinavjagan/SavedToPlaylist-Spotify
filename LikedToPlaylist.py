##############################################################################################################
#final file
import time
import os
import threading
import uuid
import sqlite3
import logging
import json
import tempfile
from pathlib import Path
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.exceptions import SpotifyException, SpotifyOauthError
from urllib.parse import urljoin
from flask import Flask, request, url_for, session, redirect, render_template, jsonify
from dotenv import load_dotenv
from recommendations import MusicTasteAnalyzer, RecommendationEngine, TimeoutException

load_dotenv()

# Read Spotify app credentials from environment (support multiple common names)
CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID') or os.getenv('SPOTIPY_CLIENT_ID') or os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET') or os.getenv('SPOTIPY_CLIENT_SECRET') or os.getenv('CLIENT_SECRET')
if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError('SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set as environment variables.')

app = Flask(__name__)
app.config['SESSION_COOKIE_NAME'] = 'Spotify Cookie'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.secret_key = os.getenv('SECRET_KEY') or os.urandom(24)
TOKEN_INFO = 'token_info'
NEED_CREDS = False
PUBLIC_URL = os.getenv('PUBLIC_URL')
if PUBLIC_URL and PUBLIC_URL.startswith('https://'):
    app.config['PREFERRED_URL_SCHEME'] = 'https'
logger = logging.getLogger(__name__)

# In-memory job store for development. Replace with a DB or cache for production.
JOBS = {}

# Simple SQLite persistence for refresh tokens (keeps users from re-authorizing)
DB_PATH = os.getenv('TOKENS_DB', 'tokens.db')
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tokens (user_id TEXT PRIMARY KEY, refresh_token TEXT, updated_at INTEGER)''')
    conn.commit()
    conn.close()

def save_refresh_token(user_id, refresh_token):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO tokens (user_id, refresh_token, updated_at) VALUES (?, ?, ?)', (user_id, refresh_token, int(time.time())))
    conn.commit()
    conn.close()

def get_refresh_token(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT refresh_token FROM tokens WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

init_db()

# Cache directory for analysis data (avoid storing large data in session)
CACHE_DIR = Path(tempfile.gettempdir()) / 'spotify_analysis_cache'
CACHE_DIR.mkdir(exist_ok=True)

def save_analysis_to_cache(user_id: str, analysis: dict) -> str:
    """Save analysis data to cache and return cache key
    
    NOTE: Cache is disabled for fresh data on every request.
    This function is kept for compatibility but does not cache.
    """
    # Cache disabled - always return empty string to force fresh analysis
    logger.info("Cache disabled - will perform fresh analysis")
    return ''

def get_analysis_from_cache(cache_key: str) -> dict:
    """Retrieve analysis data from cache
    
    NOTE: Cache is disabled - always returns empty dict to force fresh analysis.
    """
    # Cache disabled - always return empty to force fresh data
    logger.info("Cache disabled - returning empty, will trigger fresh analysis")
    return {}

def cleanup_old_cache(max_age_seconds: int = 3600) -> None:
    """Remove cache files older than max_age_seconds"""
    try:
        current_time = time.time()
        for cache_file in CACHE_DIR.glob('*.json'):
            # Delete all cache files regardless of age
            cache_file.unlink(missing_ok=True)
            logger.info(f"Deleted cache file: {cache_file.name}")
    except Exception as e:
        logger.error('Failed to cleanup cache: %s', e)


def create_spotify_client(access_token: str, timeout: int = 8) -> spotipy.Spotify:
    """Create a Spotify client with proper timeout configuration"""
    sp = spotipy.Spotify(auth=access_token, requests_timeout=timeout)
    # Additional timeout configuration for the session
    if hasattr(sp, '_session'):
        sp._session.timeout = timeout
    return sp

# Root route - show landing page
@app.route('/')
def index():
    return render_template('home.html')

# Debug route to check redirect URI configuration
@app.route('/debug/cache')
def debug_cache():
    """Display MusicBrainz cache statistics"""
    try:
        from musicbrainz_integration import get_enricher
        enricher = get_enricher()
        cache = enricher.cache
        
        conn = sqlite3.connect(cache.db_path)
        c = conn.cursor()
        
        # Total cached artists
        c.execute('SELECT COUNT(*) FROM mb_artists')
        total_artists = c.fetchone()[0]
        
        # Recent artists (last 7 days)
        week_ago = int(time.time()) - 7*24*60*60
        c.execute('SELECT COUNT(*) FROM mb_artists WHERE cached_at > ?', (week_ago,))
        recent_artists = c.fetchone()[0]
        
        # Artists with genres
        c.execute('SELECT COUNT(*) FROM mb_artists WHERE genres != ""')
        artists_with_genres = c.fetchone()[0]
        
        # Artists with tags
        c.execute('SELECT COUNT(*) FROM mb_artists WHERE tags != ""')
        artists_with_tags = c.fetchone()[0]
        
        # Average rating
        c.execute('SELECT AVG(rating) FROM mb_artists WHERE rating > 0')
        avg_rating = c.fetchone()[0] or 0
        
        conn.close()
        
        import os
        cache_size = os.path.getsize(cache.db_path) if os.path.exists(cache.db_path) else 0
        cache_size_mb = cache_size / (1024 * 1024)
        
        return jsonify({
            'status': '✅ MusicBrainz Integration Active',
            'cache': {
                'total_cached_artists': total_artists,
                'cached_this_week': recent_artists,
                'artists_with_genres': artists_with_genres,
                'artists_with_tags': artists_with_tags,
                'average_rating': round(avg_rating, 1),
                'cache_file_size_mb': round(cache_size_mb, 2),
                'cache_retention_days': 30
            },
            'performance': {
                'estimated_cache_hit_rate': f"{min(95, (total_artists / 50) * 100):.0f}%",
                'avg_new_lookups_per_recommendation': max(1, 5 - int(total_artists / 10))
            }
        })
    except Exception as e:
        return jsonify({
            'status': '⚠️ MusicBrainz not available',
            'error': str(e)
        }), 500

@app.route('/debug/config')
def debug_config():
    """Display current OAuth configuration for debugging"""
    # Determine mode the same way create_spotify_oauth does
    is_local = os.getenv('FLASK_ENV') == 'development' or not PUBLIC_URL
    
    if is_local:
        redirect_uri = url_for('redirect_page', _external=True, _scheme='http')
        mode = "LOCAL DEVELOPMENT"
    else:
        redirect_uri = f"{PUBLIC_URL.rstrip('/')}/redirect"
        mode = "PRODUCTION"
    
    # Get what Flask thinks the external URL is
    flask_external = url_for('redirect_page', _external=True)
    
    return jsonify({
        'status': '✅ Configuration Check',
        'mode': mode,
        'redirect_uri': redirect_uri,
        'flask_env': os.getenv('FLASK_ENV', 'not set'),
        'public_url': PUBLIC_URL if PUBLIC_URL else 'NOT SET',
        'flask_detected_url': flask_external,
        'client_id': CLIENT_ID[:15] + '...' if CLIENT_ID else '❌ NOT SET',
        'client_secret': '✅ SET' if CLIENT_SECRET else '❌ NOT SET',
        'instructions': {
            'step_1': f'Copy this redirect_uri: {redirect_uri}',
            'step_2': 'Go to https://developer.spotify.com/dashboard',
            'step_3': 'Click your app → Edit Settings → Redirect URIs',
            'step_4': f'Add EXACTLY: {redirect_uri}',
            'step_5': 'Click ADD, then SAVE',
            'step_6': 'Try logging in again'
        },
        'local_development_setup': {
            'note': 'You are in LOCAL MODE',
            'make_sure': [
                'Your .env file has FLASK_ENV=development',
                'Your .env does NOT have PUBLIC_URL set (or set to http://localhost:5000)',
                f'Spotify Dashboard has this redirect URI: {redirect_uri}',
                'You are accessing the app via the same URL (127.0.0.1:5000 or localhost:5000)'
            ]
        } if is_local else {
            'note': 'You are in PRODUCTION MODE',
            'make_sure': [
                'PUBLIC_URL environment variable is set correctly',
                'PUBLIC_URL does not have trailing slash',
                'PUBLIC_URL uses https:// (not http://)',
                f'Spotify Dashboard has this redirect URI: {redirect_uri}'
            ]
        }
    })

# Route to display the form for entering client_id and client_secret
@app.route('/config', methods=['GET', 'POST'])
def configure_app():
    # Always create playlist from the user's Liked Songs; playlist name is auto-generated.
    # Note: CLIENT_ID and CLIENT_SECRET should be set via environment variables
    # This route is for user preferences only, not for setting credentials
    if request.method == 'POST':
        # Auto-generate playlist name using today's date to avoid duplicates
        from datetime import datetime
        session['playlist_name'] = f"Liked Songs - {datetime.now().strftime('%Y-%m-%d')}"
        is_public = request.form.get('is_public', 'on')
        session['playlist_public'] = True if is_public == 'on' else False
        return redirect(url_for('login'))
    return render_template('config.html', need_creds=NEED_CREDS)


@app.route('/start')
def start():
    # Single-click entry point: set defaults and begin login
    from datetime import datetime
    session['playlist_name'] = f"Liked Songs - {datetime.now().strftime('%Y-%m-%d')}"
    session['playlist_public'] = True
    return redirect(url_for('login'))

# Route to handle logging in
@app.route('/login')
def login():
    # Create a SpotifyOAuth instance and get the authorization URL
    try:
        spotify_oauth = create_spotify_oauth()
        auth_url = spotify_oauth.get_authorize_url()
        # Log the redirect URI being used for debugging
        logger.info(f"Initiating login with redirect_uri: {spotify_oauth.redirect_uri}")
        # Redirect the user to the authorization URL
        return redirect(auth_url)
    except Exception as e:
        logger.error(f"Error creating Spotify OAuth: {e}")
        return render_template(
            'error.html',
            title='Configuration Error',
            message=f'Failed to initiate Spotify login. Error: {str(e)}. Please check your app configuration.'
        ), 500

# Route to handle the redirect URI after authorization
@app.route('/redirect')
def redirect_page():
    error = request.args.get('error')
    if error:
        logger.warning('Spotify authorization returned error=%s', error)
        return render_template(
            'error.html',
            title='Spotify Authorization Error',
            message='Spotify reported an error while authorizing your account. Please try again.'
        )

    code = request.args.get('code')
    if not code:
        logger.warning('Spotify redirect missing code. Params=%s', dict(request.args))
        return render_template(
            'error.html',
            title='Missing Authorization Code',
            message='We did not receive the authorization code from Spotify. Please start the sign-in again.'
        )

    spotify_oauth = create_spotify_oauth()
    redirect_uri_used = spotify_oauth.redirect_uri
    
    logger.info(f"Processing OAuth callback - redirect_uri being used: {redirect_uri_used}")
    logger.info(f"PUBLIC_URL environment variable: {PUBLIC_URL}")
    logger.info(f"Authorization code received: {code[:20]}...")
    
    try:
        # Force token exchange to avoid returning a cached token from another user
        token_info = spotify_oauth.get_access_token(code, check_cache=False)
    except SpotifyOauthError as exc:
        error_str = str(exc).lower()
        logger.error(f'Spotify OAuth Error: {exc}')
        logger.error(f'Error details - redirect_uri used: {redirect_uri_used}')
        logger.error(f'Error details - PUBLIC_URL: {PUBLIC_URL}')
        
        # Check for redirect URI mismatch specifically
        if 'redirect_uri' in error_str or 'invalid_request' in error_str:
            redirect_uri = spotify_oauth.redirect_uri
            return render_template(
                'error.html',
                title='❌ Redirect URI Mismatch',
                message=(
                    f'The redirect URI is not registered in your Spotify App.\n\n'
                    f'━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
                    f'Current redirect URI:\n'
                    f'{redirect_uri}\n'
                    f'━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n'
                    f'FIX THIS NOW:\n\n'
                    f'1. Go to: https://developer.spotify.com/dashboard\n'
                    f'2. Click your app name\n'
                    f'3. Click "Edit Settings" (green button)\n'
                    f'4. Scroll to "Redirect URIs"\n'
                    f'5. Copy and paste this EXACT URI:\n'
                    f'   {redirect_uri}\n'
                    f'6. Click "ADD"\n'
                    f'7. Click "SAVE" at the bottom\n\n'
                    f'Then refresh this page and try again.\n\n'
                    f'DEBUG INFO:\n'
                    f'PUBLIC_URL: {PUBLIC_URL or "NOT SET"}\n'
                    f'Error: {exc}'
                )
            ), 400
        
        return render_template(
            'error.html',
            title='Authorization Failed',
            message=f'Spotify rejected the authorization code. Error: {exc}\n\nPlease restart the sign-in flow and try again.'
        ), 400
    except (ConnectionError, TimeoutError):
        logger.exception('Network error during Spotify authorization')
        return render_template(
            'error.html',
            title='Authorization Failed',
            message='Network error during authorization. Please check your connection and try again.'
        ), 500
    except Exception:
        logger.exception('Unexpected error exchanging Spotify authorization code')
        return render_template(
            'error.html',
            title='Authorization Failed',
            message='We could not complete the Spotify login. Please start over and try again.'
        ), 500

    try:
        sp = create_spotify_client(token_info['access_token'])
        user_info = sp.current_user()
        user_id = user_info['id']
    except SpotifyException as exc:
        logger.warning('Spotify profile lookup failed: %s', exc)
        message = 'We could not read your Spotify profile after authorizing. Please retry the login.'
        if getattr(exc, 'http_status', None) == 403 and 'user may not be registered' in str(exc).lower():
            message = (
                "Spotify reports this account is not approved for the app yet. "
                "Add the user under Users and Access in developer.spotify.com before retrying."
            )
        return render_template(
            'error.html',
            title='Profile Lookup Failed',
            message=message
        ), 403
    except (ConnectionError, TimeoutError):
        logger.exception('Network error fetching Spotify profile')
        return render_template(
            'error.html',
            title='Profile Lookup Failed',
            message='Network error reading your profile. Please check your connection and try again.'
        ), 500
    except Exception:
        logger.exception('Failed to fetch Spotify profile for authenticated user')
        return render_template(
            'error.html',
            title='Profile Lookup Failed',
            message='We could not read your Spotify profile after authorizing. Please retry the login.'
        ), 500

    playlist_name = session.get('playlist_name')
    playlist_public = session.get('playlist_public', True)

    session.clear()
    session[TOKEN_INFO] = token_info
    session['user_id'] = user_id
    if playlist_name:
        session['playlist_name'] = playlist_name
        session['playlist_public'] = playlist_public

    if token_info.get('refresh_token'):
        save_refresh_token(user_id, token_info.get('refresh_token'))

    return redirect(url_for('progress'))


@app.route('/progress')
def progress():
    # Page shows progress and will start the background job via JS
    playlist_name = session.get('playlist_name', 'cadence')
    return render_template('progress.html', playlist_name=playlist_name)


def create_playlist_job(job_id, expected_user_id, token_info, playlist_name, playlist_public):
    """
    Create a playlist for the user using their own access token.
    
    Args:
        job_id: Unique job identifier
        expected_user_id: The Spotify user ID this job should create playlist for
        token_info: OAuth token info containing the user's access token
        playlist_name: Name for the new playlist
        playlist_public: Whether playlist should be public
    """
    try:
        JOBS[job_id]['status'] = 'working'
        
        # Create Spotify instance with the user's access token (NOT app credentials)
        sp = create_spotify_client(token_info['access_token'])
        
        # Verify we have the correct user's token
        current_user = sp.current_user()
        actual_user_id = current_user['id']
        
        # SECURITY CHECK: Ensure token matches expected user
        if actual_user_id != expected_user_id:
            error_msg = (
                f'Token user mismatch! Expected {expected_user_id}, got {actual_user_id}. '
                f'This is a security issue - playlist would be created in wrong account!'
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        JOBS[job_id]['user_id'] = actual_user_id
        
        # Create a NEW playlist in THIS user's account
        new_playlist = sp.user_playlist_create(actual_user_id, playlist_name, playlist_public)
        new_playlist_id = new_playlist['id']
        new_playlist_url = new_playlist.get('external_urls', {}).get('spotify')

        JOBS[job_id]['total'] = 0
        JOBS[job_id]['progress'] = 0

        # Fetch THIS user's liked songs using their access token
        seen = set()
        offset = 0
        limit = 50
        while True:
            # This uses the user's token, so it gets THEIR liked songs
            saved = sp.current_user_saved_tracks(limit=limit, offset=offset)
            items = saved.get('items', [])
            if not items:
                break
            uris = []
            for item in items:
                uri = item['track']['uri']
                if uri not in seen:
                    seen.add(uri)
                    uris.append(uri)
            if uris:
                # Add tracks to THIS user's playlist
                for i in range(0, len(uris), 100):
                    chunk = uris[i:i+100]
                    sp.user_playlist_add_tracks(actual_user_id, new_playlist_id, chunk)
                    JOBS[job_id]['progress'] += len(chunk)
            offset += limit
        
        JOBS[job_id]['total'] = JOBS[job_id]['progress']
        JOBS[job_id]['status'] = 'done'
        JOBS[job_id]['playlist_url'] = new_playlist_url
        JOBS[job_id]['playlist_name'] = playlist_name
        
    except SpotifyException as exc:
        JOBS[job_id]['status'] = 'error'
        message = str(exc)
        if getattr(exc, 'http_status', None) == 403 and 'user may not be registered' in str(exc).lower():
            message = (
                'Spotify blocked the playlist creation because this account is not added '
                'as a tester for the app in developer.spotify.com.'
            )
        JOBS[job_id]['message'] = message
        logger.error('Spotify error creating playlist: %s', message)
    except (ValueError, ConnectionError, TimeoutError) as e:
        JOBS[job_id]['status'] = 'error'
        JOBS[job_id]['message'] = str(e)
        logger.error('Error creating playlist: %s', e)
    except Exception:
        JOBS[job_id]['status'] = 'error'
        JOBS[job_id]['message'] = 'An unexpected error occurred. Please try again.'
        logger.exception('Unexpected error in create_playlist_job')

@app.route('/saveLiked')
def save_liked():
    try: 
        token_info = get_token()
    except Exception:
        # If the token info is not found, redirect the user to the login route
        logger.warning('User not logged in or token invalid')
        return redirect("/")

    # Create a Spotipy instance with the access token
    sp = create_spotify_client(token_info['access_token'])
    user_id = sp.current_user()['id']
    # Create playlist with chosen name and privacy
    playlist_name = session.get('playlist_name', 'cadence')
    playlist_public = session.get('playlist_public', True)
    new_playlist = sp.user_playlist_create(user_id, playlist_name, playlist_public)
    new_playlist_id = new_playlist['id']
    new_playlist_url = new_playlist.get('external_urls', {}).get('spotify')

    seen = set()
    offset = 0
    limit = 50
    while True:
        saved = sp.current_user_saved_tracks(limit=limit, offset=offset)
        items = saved.get('items', [])
        if not items:
            break
        uris = []
        for item in items:
            uri = item['track']['uri']
            if uri not in seen:
                seen.add(uri)
                uris.append(uri)
        if uris:
            for i in range(0, len(uris), 100):
                chunk = uris[i:i+100]
                sp.user_playlist_add_tracks(user_id, new_playlist['id'], chunk)
        offset += limit

    return render_template('saved.html', playlist_name=playlist_name, playlist_url=new_playlist_url)


@app.route('/start_save', methods=['POST'])
def start_save():
    # Start background job and return job id
    try:
        token_info = get_token()
        user_id = session.get('user_id')
        
        if not user_id:
            # If user_id not in session, get it from the token
            sp = create_spotify_client(token_info['access_token'])
            user_id = sp.current_user()['id']
            session['user_id'] = user_id
            
    except Exception as e:
        return jsonify({'error': 'not_logged_in', 'message': str(e)}), 401

    playlist_name = session.get('playlist_name', 'cadence')
    playlist_public = session.get('playlist_public', True)
    job_id = str(uuid.uuid4())
    
    # Store user_id with the job so we can track it
    JOBS[job_id] = {
        'status': 'pending', 
        'progress': 0, 
        'total': None,
        'user_id': user_id,  # Track which user this job is for
        'created_at': int(time.time())
    }
    
    # Pass user_id explicitly to the job
    thread = threading.Thread(
        target=create_playlist_job, 
        args=(job_id, user_id, token_info, playlist_name, playlist_public)
    )
    thread.start()
    return jsonify({'job_id': job_id})


@app.route('/job_status')
def job_status():
    job_id = request.args.get('job_id')
    if not job_id or job_id not in JOBS:
        return jsonify({'error': 'job_not_found'}), 404
    return jsonify(JOBS[job_id])

def get_token():
    """Get the current user's valid access token from session"""
    token_info = session.get(TOKEN_INFO, None)
    
    if not token_info:
        # Token not in session, try to recover using stored refresh token
        user_id = session.get('user_id')
        if user_id:
            refresh_token = get_refresh_token(user_id)
            if refresh_token:
                spotify_oauth = create_spotify_oauth()
                try:
                    token_info = spotify_oauth.refresh_access_token(refresh_token)
                    session[TOKEN_INFO] = token_info
                    return token_info
                except Exception as e:
                    raise Exception(f'Failed to refresh token: {str(e)}')
        raise Exception('User not logged in - no token in session')
    
    # Check if the token is expired and refresh it if necessary
    now = int(time.time())
    is_expired = token_info.get('expires_at', 0) - now < 60
    
    if is_expired:
        # Token expired, refresh it
        spotify_oauth = create_spotify_oauth()
        try:
            token_info = spotify_oauth.refresh_access_token(token_info.get('refresh_token'))
            session[TOKEN_INFO] = token_info
            
            # Persist refreshed refresh_token if returned
            user_id = session.get('user_id')
            if 'refresh_token' in token_info and user_id:
                save_refresh_token(user_id, token_info['refresh_token'])
        except Exception as e:
            raise Exception(f'Failed to refresh expired token: {str(e)}')
    
    return token_info

def create_spotify_oauth(client_id=None, client_secret=None):
    # Use an in-memory cache so tokens do not leak across different user sessions
    # Construct redirect URI carefully to match Spotify Dashboard settings
    
    # Determine if running locally or in production
    is_local = os.getenv('FLASK_ENV') == 'development' or not PUBLIC_URL
    
    if is_local:
        # Local development: Use Flask's url_for to get the actual host
        # This will be http://127.0.0.1:5000/redirect or http://localhost:5000/redirect
        redirect_uri = url_for('redirect_page', _external=True, _scheme='http')
        logger.info(f"🏠 LOCAL MODE - Using redirect URI: {redirect_uri}")
    else:
        # Production: Use the configured PUBLIC_URL
        base_url = PUBLIC_URL.rstrip('/')
        redirect_uri = f"{base_url}/redirect"
        logger.info(f"🌐 PRODUCTION MODE - Using redirect URI: {redirect_uri}")
    
    logger.info(f"Environment: FLASK_ENV={os.getenv('FLASK_ENV')}, PUBLIC_URL={PUBLIC_URL}")
    
    return SpotifyOAuth(
        client_id=client_id or CLIENT_ID,
        client_secret=client_secret or CLIENT_SECRET,
        redirect_uri=redirect_uri,
        scope='user-library-read playlist-modify-public playlist-modify-private user-top-read',
        cache_handler=MemoryCacheHandler()
    )

# ========== RECOMMENDATION SYSTEM ROUTES ==========

@app.route('/recommendations')
def recommendations_page():
    """Display the recommendations dashboard"""
    try:
        token_info = get_token()
    except Exception:
        # User not logged in - redirect to login
        return redirect('/login')
    
    if not token_info:
        return redirect('/login')
    return render_template('recommendations.html')

@app.route('/api/analyze-taste', methods=['POST'])
def analyze_taste():
    """Analyze user's music taste - OPTIMIZED to prevent worker timeouts
    
    CRITICAL: Worker timeout is 45 seconds. This endpoint MUST complete in < 25 seconds.
    All settings are ULTRA-CONSERVATIVE to ensure completion.
    """
    try:
        token_info = get_token()
        if not token_info:
            return jsonify({'error': 'Not authenticated'}), 401
        
        # Use 2-second timeout per request (critical for preventing hangs)
        sp = create_spotify_client(token_info['access_token'], timeout=2)
        
        # Get parameters
        data = request.get_json() or {}
        # PLAYLISTS DISABLED BY DEFAULT (major timeout source)
        include_playlists = data.get('include_playlists', False)
        
        logger.info("=== ANALYSIS START === playlists=%s", include_playlists)
        start_time = time.time()
        
        # Initialize analyzer with 2-second request timeout
        analyzer = MusicTasteAnalyzer(sp, request_timeout=2)
        
        try:
            # ULTRA-CONSERVATIVE LIMITS (to prevent worker timeout):
            # - 15 liked songs (single API call, ~2 seconds)
            # - NO playlists by default
            # - 20 second max (25 second buffer before 45s worker timeout)
            analysis = analyzer.analyze_taste(
                include_playlists=include_playlists,
                playlist_limit=0 if not include_playlists else 1,  # Max 1 playlist if requested
                tracks_per_playlist=3,  # Only 3 tracks if playlists enabled
                liked_songs_limit=15,  # Only 15 liked songs (fast, single call)
                max_analysis_time=20  # HARD LIMIT: 20 seconds (25s buffer before timeout)
            )
        except TimeoutException as e:
            logger.error("=== TIMEOUT === %s", e)
            return jsonify({'error': 'Analysis timeout. Please try again without playlists.'}), 408
        
        elapsed_time = time.time() - start_time
        logger.info("Taste analysis completed in %.2f seconds", elapsed_time)
        
        # Check if we got any error in the analysis
        if analysis.get('error'):
            return jsonify(analysis), 400
        
        # Store analysis in cache instead of session to avoid size limits
        user_id = session.get('user_id')
        if not user_id:
            user_profile = sp.current_user()
            user_id = user_profile['id']
            session['user_id'] = user_id
        
        cache_key = save_analysis_to_cache(user_id, analysis)
        if cache_key:
            session['analysis_cache_key'] = cache_key
        
        return jsonify(analysis)
        
    except SpotifyException as e:
        logger.error("Spotify API error during taste analysis: %s", e)
        error_message = 'Spotify API error occurred'
        if hasattr(e, 'http_status'):
            if e.http_status == 429:
                error_message = 'Rate limit exceeded. Please wait a moment and try again.'
            elif e.http_status == 403:
                error_message = 'Permission denied. Please ensure the app has the required permissions.'
        return jsonify({'error': error_message, 'details': str(e)}), 500
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.error("Network/timeout error during taste analysis: %s", e)
        return jsonify({'error': 'Network error or timeout. Please check your connection and try again.'}), 500
    except Exception as e:
        logger.exception('Unexpected error analyzing taste')
        return jsonify({'error': 'An unexpected error occurred during analysis. Please try again.', 'details': str(e) if app.debug else None}), 500

@app.route('/api/generate-recommendations', methods=['POST'])
def generate_recommendations():
    """Generate recommendations and create playlist"""
    try:
        token_info = get_token()
        if not token_info:
            return jsonify({'error': 'Not authenticated'}), 401
        
        sp = create_spotify_client(token_info['access_token'])
        
        # Get parameters
        data = request.get_json() or {}
        playlist_name = data.get('playlist_name', 'My Recommendations')
        track_limit = min(int(data.get('track_limit', 20)), 100)  # Default 20, max 100
        use_audio_features = data.get('use_audio_features', True)
        public = data.get('public', True)
        
        # Get user preferences
        preferences = {
            'mood': data.get('mood', 'any'),
            'era': data.get('era', 'any'),
            'discovery': int(data.get('discovery', 50))  # 0-100, default 50
        }
        
        logger.info("User preferences: mood=%s, era=%s, discovery=%d", 
                   preferences['mood'], preferences['era'], preferences['discovery'])
        
        # ALWAYS run fresh analysis (cache disabled)
        user_id = session.get('user_id')
        if not user_id:
            user_profile = sp.current_user()
            user_id = user_profile['id']
            session['user_id'] = user_id
        
        # Cache is disabled - always run fresh analysis
        logger.info("="*60)
        logger.info("FLASK: Starting fresh analysis (cache disabled)")
        logger.info("User ID: %s", user_id)
        logger.info("="*60)
        
        analyzer = MusicTasteAnalyzer(sp, request_timeout=2)
        try:
            # MINIMAL analysis: 15 liked songs only, no playlists
            analysis = analyzer.analyze_taste(
                include_playlists=False,  # NEVER use playlists here
                playlist_limit=0,
                tracks_per_playlist=0,
                liked_songs_limit=15,  # Only 15 liked songs (fast)
                max_analysis_time=15  # 15 second hard limit
            )
            logger.info("="*60)
            logger.info("FLASK: Analysis complete")
            logger.info("Result: track_count=%s, unique_artists=%s, genres=%s", 
                       analysis.get('track_count'),
                       analysis.get('unique_artists'),
                       len(analysis.get('top_genres', [])))
            logger.info("Top artist IDs: %s", analysis.get('top_artist_ids', [])[:3])
            logger.info("Genre seeds: %s", analysis.get('genre_seeds', [])[:5])
            logger.info("="*60)
        except TimeoutException as e:
            logger.error("=== TIMEOUT === During recommendation analysis: %s", e)
            return jsonify({'error': 'Analysis timeout. Please try again.'}), 408
        
        # Check if analysis has errors (but still try to generate recommendations)
        if analysis.get('error') and not analysis.get('top_artist_ids'):
            return jsonify({'error': analysis.get('error', 'Analysis failed')}), 400
        
        # Disable audio features if they failed (403 errors)
        has_audio_features = bool(analysis.get('avg_audio_features'))
        if not has_audio_features and use_audio_features:
            logger.warning("Audio features not available (403 error) - generating recommendations without them")
            use_audio_features = False
        
        # Generate recommendations
        logger.info("="*60)
        logger.info("FLASK: Generating recommendations")
        logger.info("Parameters: limit=%d, use_audio_features=%s, public=%s", 
                   track_limit, use_audio_features, public)
        logger.info("="*60)
        
        engine = RecommendationEngine(sp)
        recommendations = engine.generate_recommendations(
            analysis=analysis,
            limit=track_limit,
            include_audio_targets=use_audio_features,
            preferences=preferences
        )
        
        logger.info("="*60)
        logger.info("FLASK: Recommendation generation complete")
        logger.info("Recommendations received: %d tracks", len(recommendations))
        logger.info("="*60)
        
        if not recommendations:
            error_msg = 'No recommendations could be generated. '
            if not analysis.get('top_artist_ids'):
                error_msg += 'Unable to find artists from your library. Please add more liked songs to your Spotify account.'
            elif not analysis.get('genre_seeds'):
                error_msg += 'Unable to determine music genres. Try adding more varied music to your library.'
            else:
                error_msg += 'The Spotify API did not return any recommendations. Try different settings or add your email to the Spotify Developer Dashboard allowed users list.'
            logger.error("No recommendations generated: %s", error_msg)
            return jsonify({'error': error_msg}), 400
        
        # Create playlist
        result = engine.create_recommendation_playlist(
            user_id=user_id,
            recommendations=recommendations,
            playlist_name=playlist_name,
            public=public
        )
        
        if result.get('error'):
            return jsonify(result), 400
        
        return jsonify(result)
        
    except SpotifyException as e:
        logger.error("Spotify API error during recommendation generation: %s", e)
        error_message = 'Spotify API error occurred'
        if hasattr(e, 'http_status'):
            if e.http_status == 429:
                error_message = 'Rate limit exceeded. Please wait a moment and try again.'
            elif e.http_status == 403:
                error_message = ('Permission denied by Spotify. Your app is in Development Mode. '
                               'Go to https://developer.spotify.com/dashboard → Your App → Settings → Users and Access '
                               '→ Add your Spotify email address to the allowed users list.')
        return jsonify({'error': error_message, 'details': str(e) if app.debug else None}), 500
    except (ConnectionError, TimeoutError) as e:
        logger.error("Network error during recommendation generation: %s", e)
        return jsonify({'error': 'Network error. Please check your connection and try again.'}), 500
    except Exception as e:
        logger.exception('Unexpected error generating recommendations')
        return jsonify({'error': 'An unexpected error occurred. Please try again.', 'details': str(e) if app.debug else None}), 500

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_ENV') != 'production'
    # Use port 8000 for local development to avoid conflicts with macOS AirPlay Receiver
    port = int(os.getenv('PORT', 8000))
    app.run(debug=debug_mode, port=port, host='127.0.0.1')
