##############################################################################################################
#final file
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, request, url_for, session, redirect, render_template

app = Flask(__name__)
app.config['SESSION_COOKIE_NAME'] = 'Spotify Cookie'
app.secret_key = 'YOUR_SECRET_KEY'
TOKEN_INFO = 'token_info'

# Route to display the form for entering client_id and client_secret
@app.route('/config', methods=['GET', 'POST'])
def configure_app():
    if request.method == 'POST':
        global client_i
        global client_secre
        client_i = request.form.get('client_id')
        client_secre= request.form.get('client_secret')
        # Update the create_spotify_oauth function with the entered values
        app.spotify_oauth = create_spotify_oauth()
        return redirect(url_for('login'))
    return render_template('config.html')

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
    session.clear()
    # Get the authorization code from the request parameters
    code = request.args.get('code')
    # Exchange the authorization code for an access token and refresh token
    token_info = create_spotify_oauth().get_access_token(code)
    # Save the token info in the session
    session[TOKEN_INFO] = token_info
    # Redirect the user to the save_liked route
    return redirect(url_for('save_liked', _external=True))

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
    # Get the user's playlists
    new_playlist = sp.user_playlist_create(user_id, 'Saved', True)
    new_playlist_id = new_playlist['id']
    temp=set()
    for i in range(28):
        saved = sp.current_user_saved_tracks(50, 50 * i)
        song_uris = set()
        for song in saved['items']:
            song_uri = song['track']['uri']
            if song_uri not in temp:
                song_uris.add(song_uri)
        if song_uris:
            sp.user_playlist_add_tracks(user_id, new_playlist_id, song_uris, None)


    return render_template('saved.html')

def get_token():
    token_info = session.get(TOKEN_INFO, None)
    if not token_info:
        # If the token info is not found, redirect the user to the login route
        redirect(url_for('login', _external=False))
    # Check if the token is expired and refresh it if necessary
    now = int(time.time())
    is_expired = token_info['expires_at'] - now < 60
    if is_expired:
        spotify_oauth = create_spotify_oauth()
        token_info = spotify_oauth.refresh_access_token(token_info['refresh_token'])
    return token_info

def create_spotify_oauth(client_id=None, client_secret=None):
    
    return SpotifyOAuth(
        client_id=client_i,
        client_secret=client_secre,
        redirect_uri=url_for('redirect_page', _external=True),
        scope='user-library-read playlist-modify-public playlist-modify-private'
    )

app.run(debug=True)
