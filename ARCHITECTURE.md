# System Architecture Diagram

## Complete Application Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────────┐ │
│  │  home.html   │  │  config.html     │  │  recommendations.html │ │
│  │              │  │                  │  │                       │ │
│  │ - Welcome    │  │ - Playlist form  │  │ - Taste analysis      │ │
│  │ - Features   │  │ - Name/privacy   │  │ - Top genres          │ │
│  │ - Start CTA  │  │                  │  │ - Audio profile       │ │
│  │              │  │                  │  │ - Generate form       │ │
│  └──────┬───────┘  └────────┬─────────┘  └──────────┬────────────┘ │
│         │                   │                        │              │
└─────────┼───────────────────┼────────────────────────┼──────────────┘
          │                   │                        │
          ▼                   ▼                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FLASK APPLICATION                               │
│                    (LikedToPlaylist.py)                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    EXISTING ROUTES                           │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │  GET  /           → home page                               │   │
│  │  GET  /start      → config form                             │   │
│  │  GET  /login      → OAuth redirect                          │   │
│  │  GET  /redirect   → OAuth callback                          │   │
│  │  POST /create     → create playlist job                     │   │
│  │  GET  /status     → check job status                        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                     NEW ROUTES                               │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │  GET  /recommendations       → dashboard page               │   │
│  │  POST /api/analyze-taste     → analyze music library        │   │
│  │  POST /api/generate-recommendations → create playlist       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                       │
└───────────────────────────┬───────────────────────────────────────┬─┘
                            │                                       │
                            ▼                                       ▼
              ┌──────────────────────────┐      ┌────────────────────────────┐
              │  ORIGINAL FUNCTIONALITY   │      │   NEW RECOMMENDATION      │
              │                          │      │        SYSTEM             │
              ├──────────────────────────┤      ├────────────────────────────┤
              │                          │      │                            │
              │  ┌────────────────────┐ │      │  ┌──────────────────────┐ │
              │  │ SpotifyOAuth       │ │      │  │ MusicTasteAnalyzer   │ │
              │  │ - Login/Auth       │ │      │  │                      │ │
              │  │ - Token mgmt       │ │      │  │ - Get playlists      │ │
              │  └────────────────────┘ │      │  │ - Get liked songs    │ │
              │                          │      │  │ - Extract artists    │ │
              │  ┌────────────────────┐ │      │  │ - Get genres         │ │
              │  │ create_playlist_   │ │      │  │ - Audio features     │ │
              │  │ job()              │ │      │  │ - Taste profile      │ │
              │  │ - Fetch liked      │ │      │  └──────────────────────┘ │
              │  │ - Create playlist  │ │      │                            │
              │  │ - Add tracks       │ │      │  ┌──────────────────────┐ │
              │  │ - Background job   │ │      │  │ RecommendationEngine │ │
              │  └────────────────────┘ │      │  │                      │ │
              │                          │      │  │ - Get genre seeds    │ │
              │  ┌────────────────────┐ │      │  │ - Build params       │ │
              │  │ Token persistence  │ │      │  │ - Get recommends     │ │
              │  │ - SQLite DB        │ │      │  │ - Create playlist    │ │
              │  │ - Refresh tokens   │ │      │  │ - Add tracks         │ │
              │  └────────────────────┘ │      │  └──────────────────────┘ │
              │                          │      │                            │
              └──────────┬───────────────┘      └─────────────┬──────────────┘
                         │                                    │
                         │                                    │
                         └────────────────┬───────────────────┘
                                          │
                                          ▼
                         ┌────────────────────────────────────┐
                         │       SPOTIFY WEB API              │
                         ├────────────────────────────────────┤
                         │                                    │
                         │  /me/tracks                        │
                         │  /me/playlists                     │
                         │  /playlists/{id}/tracks            │
                         │  /artists                          │
                         │  /audio-features                   │
                         │  /recommendations/available-...    │
                         │  /recommendations                  │
                         │  /users/{id}/playlists             │
                         │                                    │
                         └────────────────────────────────────┘
```

## Data Flow - Recommendation System

```
USER ACTION: Click "Analyze & Generate Playlist"
    │
    ├─► STEP 1: Analyze Taste
    │   │
    │   ├─► Fetch liked songs (up to 500)
    │   │   GET /me/tracks?limit=50&offset=0...
    │   │   Response: [{track}, {track}, ...]
    │   │
    │   ├─► Fetch user playlists (up to 10)
    │   │   GET /me/playlists?limit=50
    │   │   Response: [{playlist}, {playlist}, ...]
    │   │
    │   ├─► For each playlist, get tracks (up to 50)
    │   │   GET /playlists/{id}/tracks?limit=100
    │   │   Response: [{track}, {track}, ...]
    │   │
    │   ├─► Extract unique artist IDs
    │   │   artists = {artist_id_1, artist_id_2, ...}
    │   │
    │   ├─► Get artist genres (batch 50)
    │   │   GET /artists?ids=id1,id2,...
    │   │   Response: [{genres: [...]}, ...]
    │   │   Process: Count genre frequency
    │   │
    │   ├─► Get audio features (batch 100)
    │   │   GET /audio-features?ids=track1,track2,...
    │   │   Response: [{energy: 0.8, ...}, ...]
    │   │   Process: Calculate averages
    │   │
    │   └─► Return analysis
    │       {
    │         track_count: 450,
    │         unique_artists: 120,
    │         top_genres: [...],
    │         avg_audio_features: {...}
    │       }
    │
    ├─► STEP 2: Display Analysis
    │   │
    │   ├─► Update dashboard UI
    │   │   - Show track count
    │   │   - Display top genres
    │   │   - Show audio profile bars
    │   │
    │   └─► Store in session
    │       session['taste_analysis'] = analysis
    │
    ├─► STEP 3: Generate Recommendations
    │   │
    │   ├─► Get available genre seeds
    │   │   GET /recommendations/available-genre-seeds
    │   │   Response: {genres: ["rock", "pop", ...]}
    │   │
    │   ├─► Build recommendation params
    │   │   {
    │   │     seed_artists: "artist1,artist2",
    │   │     seed_genres: "genre1,genre2,genre3",
    │   │     target_energy: 0.72,
    │   │     target_danceability: 0.65,
    │   │     limit: 30
    │   │   }
    │   │
    │   ├─► Request recommendations
    │   │   GET /recommendations?seed_artists=...&limit=30
    │   │   Response: {tracks: [{track}, {track}, ...]}
    │   │
    │   └─► Filter & return tracks
    │       recommendations = [track1, track2, ...]
    │
    └─► STEP 4: Create Playlist
        │
        ├─► Create new playlist
        │   POST /users/{user_id}/playlists
        │   Body: {name: "...", public: true}
        │   Response: {id: "playlist_id", ...}
        │
        ├─► Add tracks (batch 100)
        │   POST /playlists/{id}/tracks
        │   Body: {uris: ["spotify:track:...", ...]}
        │   Response: {snapshot_id: "..."}
        │
        └─► Return success
            {
              playlist_id: "...",
              playlist_url: "https://...",
              track_count: 30
            }
```

## Component Interactions

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND                                 │
│  recommendations.html                                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  JavaScript                                               │  │
│  │  - Form submission handler                                │  │
│  │  - API calls (fetch)                                      │  │
│  │  - UI updates                                             │  │
│  │  - Progress indicators                                    │  │
│  └─────────────┬────────────────────────────────────────────┘  │
└────────────────┼────────────────────────────────────────────────┘
                 │
                 │ HTTP POST /api/analyze-taste
                 │ HTTP POST /api/generate-recommendations
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                         BACKEND                                  │
│  LikedToPlaylist.py                                             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Flask Routes                                             │  │
│  │  - @app.route('/recommendations')                         │  │
│  │  - @app.route('/api/analyze-taste')                       │  │
│  │  - @app.route('/api/generate-recommendations')            │  │
│  │                                                            │  │
│  │  Authentication                                            │  │
│  │  - get_token()                                             │  │
│  │  - create_spotify_oauth()                                  │  │
│  └─────────────┬────────────────────────────────────────────┘  │
└────────────────┼────────────────────────────────────────────────┘
                 │
                 │ Creates instances
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RECOMMENDATION ENGINE                         │
│  recommendations.py                                              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  MusicTasteAnalyzer                                       │  │
│  │  ┌──────────────────────────────────────────────────┐    │  │
│  │  │ Methods:                                          │    │  │
│  │  │ - get_user_playlists()                            │    │  │
│  │  │ - get_playlist_tracks(playlist_id)                │    │  │
│  │  │ - get_liked_songs()                               │    │  │
│  │  │ - extract_artist_ids(tracks)                      │    │  │
│  │  │ - get_artist_genres(artist_ids)                   │    │  │
│  │  │ - get_track_audio_features(track_ids)             │    │  │
│  │  │ - analyze_taste()  ← Main method                  │    │  │
│  │  └──────────────────────────────────────────────────┘    │  │
│  │                                                            │  │
│  │  RecommendationEngine                                      │  │
│  │  ┌──────────────────────────────────────────────────┐    │  │
│  │  │ Methods:                                          │    │  │
│  │  │ - get_available_genres()                          │    │  │
│  │  │ - generate_recommendations(analysis)              │    │  │
│  │  │ - create_recommendation_playlist(...)  ← Main     │    │  │
│  │  └──────────────────────────────────────────────────┘    │  │
│  └─────────────┬────────────────────────────────────────────┘  │
└────────────────┼────────────────────────────────────────────────┘
                 │
                 │ Makes API calls via spotipy
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SPOTIPY CLIENT                              │
│  spotipy.Spotify(auth=token)                                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ - current_user_saved_tracks()                             │  │
│  │ - current_user_playlists()                                │  │
│  │ - playlist_items()                                         │  │
│  │ - artists()                                                │  │
│  │ - audio_features()                                         │  │
│  │ - recommendation_genre_seeds()                             │  │
│  │ - recommendations()                                        │  │
│  │ - user_playlist_create()                                   │  │
│  │ - playlist_add_items()                                     │  │
│  └─────────────┬────────────────────────────────────────────┘  │
└────────────────┼────────────────────────────────────────────────┘
                 │
                 │ HTTPS requests
                 │
                 ▼
        ┌────────────────────────┐
        │   SPOTIFY WEB API      │
        │  api.spotify.com       │
        └────────────────────────┘
```

## File Dependencies

```
LikedToPlaylist.py
    ├── imports recommendations.py
    │   ├── MusicTasteAnalyzer
    │   └── RecommendationEngine
    │
    ├── imports spotipy
    │   ├── Spotify
    │   ├── SpotifyOAuth
    │   └── SpotifyException
    │
    ├── imports flask
    │   ├── Flask
    │   ├── render_template
    │   ├── request
    │   └── session
    │
    └── renders templates
        ├── home.html
        ├── config.html
        ├── recommendations.html
        ├── progress.html
        ├── saved.html
        └── error.html
```

## Session Data Flow

```
Session Variables:
├── token_info
│   ├── access_token
│   ├── refresh_token
│   ├── expires_at
│   └── scope
│
├── user_id
│   └── Spotify user ID
│
├── playlist_name (temporary)
│   └── User's playlist name choice
│
├── playlist_public (temporary)
│   └── Public/private preference
│
└── taste_analysis (new)
    ├── track_count
    ├── unique_artists
    ├── top_genres
    ├── top_artist_ids
    ├── avg_audio_features
    └── genre_seeds
```
