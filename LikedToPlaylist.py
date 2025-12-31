##############################################################################################################
#final file
import time
import os
import threading
import uuid
import sqlite3
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import MemoryCacheHandler
from urllib.parse import urljoin
from flask import Flask, request, url_for, session, redirect, render_template, jsonify
from dotenv import load_dotenv

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

# Root route - show landing page
@app.route('/')
def index():
    return render_template('home.html')

# Route to display the form for entering client_id and client_secret
@app.route('/config', methods=['GET', 'POST'])
def configure_app():
    # Always create playlist from the user's Liked Songs; playlist name is auto-generated.
    global CLIENT_ID, CLIENT_SECRET, NEED_CREDS
    if request.method == 'POST':
        # If server needs creds, accept them from the form (dev only)
        if NEED_CREDS and request.form.get('client_id') and request.form.get('client_secret'):
            CLIENT_ID = request.form.get('client_id')
            CLIENT_SECRET = request.form.get('client_secret')
            NEED_CREDS = False
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
    auth_url = create_spotify_oauth().get_authorize_url()
    # Redirect the user to the authorization URL
    return redirect(auth_url)

# Route to handle the redirect URI after authorization
@app.route('/redirect')
def redirect_page():
    # Get the authorization code from the request parameters
    code = request.args.get('code')
    # Exchange the authorization code for an access token and refresh token
    spotify_oauth = create_spotify_oauth()
    # Force token exchange to avoid returning a cached token from another user
    token_info = spotify_oauth.get_access_token(code, check_cache=False)
    
    # Get the current user info BEFORE clearing session
    sp = spotipy.Spotify(auth=token_info['access_token'])
    try:
        user_info = sp.current_user()
        user_id = user_info['id']
    except Exception as e:
        return redirect(url_for('start'))  # Redirect to start if auth fails
    
    # Now clear and set fresh session data for this specific user
    session.clear()
    session[TOKEN_INFO] = token_info
    session['user_id'] = user_id
    
    # Save refresh token to DB for persistence across sessions
    if token_info.get('refresh_token'):
        save_refresh_token(user_id, token_info.get('refresh_token'))
    
    # Redirect the user to the progress page which will start the background job
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
        sp = spotipy.Spotify(auth=token_info['access_token'])
        
        # Verify we have the correct user's token
        current_user = sp.current_user()
        actual_user_id = current_user['id']
        
        # SECURITY CHECK: Ensure token matches expected user
        if actual_user_id != expected_user_id:
            raise Exception(
                f'Token user mismatch! Expected {expected_user_id}, got {actual_user_id}. '
                f'This is a security issue - playlist would be created in wrong account!'
            )
        
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
        
    except Exception as e:
        JOBS[job_id]['status'] = 'error'
        JOBS[job_id]['message'] = str(e)

@app.route('/saveLiked')
def save_liked():
    try: 
        token_info = get_token()
    except:
        # If the token info is not found, redirect the user to the login route
        print('User not logged in')
        return redirect("/")

    # Create a Spotipy instance with the access token
    sp = spotipy.Spotify(auth=token_info['access_token'])
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
            sp = spotipy.Spotify(auth=token_info['access_token'])
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
    redirect_uri = url_for('redirect_page', _external=True)
    if PUBLIC_URL:
        # Build redirect using the public base URL to avoid proxy scheme mismatches
        redirect_uri = urljoin(PUBLIC_URL.rstrip('/') + '/', url_for('redirect_page', _external=False).lstrip('/'))
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=redirect_uri,
        scope='user-library-read playlist-modify-public playlist-modify-private',
        cache_handler=MemoryCacheHandler()
    )

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_ENV') != 'production'
    app.run(debug=debug_mode)
