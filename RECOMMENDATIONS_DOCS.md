# 🎵 Music Recommendation System - Feature Documentation

## Overview

The recommendation system analyzes a user's music taste based on their Spotify playlists and liked songs, then generates a personalized playlist with similar tracks. This feature uses Spotify's Web API to provide intelligent music recommendations.

## Features

### 1. **Music Taste Analysis**
- Analyzes up to 500 liked songs
- Scans up to 10 playlists (50 tracks each)
- Extracts genre preferences from artists
- Calculates average audio features:
  - Energy
  - Danceability
  - Valence (happiness)
  - Acousticness
  - Speechiness
  - Tempo

### 2. **Smart Recommendations**
- Uses Spotify's recommendation algorithm
- Seeds recommendations with:
  - Top 2 artists from user's library
  - Top 5 genres (from available genre seeds)
  - Audio feature targets matching user's taste
- Generates up to 50 recommended tracks

### 3. **Automatic Playlist Creation**
- Creates a new playlist in user's Spotify account
- Adds all recommended tracks
- Customizable playlist name and visibility
- Direct link to open in Spotify

## API Endpoints

### `/recommendations`
**Method:** GET  
**Description:** Display the recommendations dashboard  
**Authentication:** Required (OAuth token)  
**Returns:** HTML page with interactive dashboard

### `/api/analyze-taste`
**Method:** POST  
**Description:** Analyze user's music taste  
**Authentication:** Required  
**Request Body:**
```json
{
  "include_playlists": true  // Optional, default: true
}
```
**Response:**
```json
{
  "track_count": 450,
  "unique_artists": 120,
  "top_genres": [
    ["indie rock", 45],
    ["electronic", 32],
    ["alternative", 28]
  ],
  "top_artist_ids": ["artist_id_1", "artist_id_2", ...],
  "avg_audio_features": {
    "energy": 0.72,
    "danceability": 0.65,
    "valence": 0.58
  },
  "genre_seeds": ["indie rock", "electronic", "alternative"]
}
```

### `/api/generate-recommendations`
**Method:** POST  
**Description:** Generate recommendations and create playlist  
**Authentication:** Required  
**Request Body:**
```json
{
  "playlist_name": "My Recommendations",  // Optional
  "track_limit": 30,                      // Optional, 10-50
  "use_audio_features": true,             // Optional, default: true
  "public": true                          // Optional, default: true
}
```
**Response:**
```json
{
  "success": true,
  "playlist_id": "spotify_playlist_id",
  "playlist_url": "https://open.spotify.com/playlist/...",
  "playlist_name": "My Recommendations",
  "track_count": 30
}
```

## File Structure

```
SavedToPlaylist-Spotify/
├── recommendations.py           # Core recommendation logic
│   ├── MusicTasteAnalyzer      # Analyzes user's music library
│   └── RecommendationEngine    # Generates recommendations
├── templates/
│   └── recommendations.html    # Dashboard UI
└── LikedToPlaylist.py          # Flask app with new routes
```

## How It Works

### Step 1: Taste Analysis
```python
analyzer = MusicTasteAnalyzer(sp)
analysis = analyzer.analyze_taste(
    include_playlists=True,
    playlist_limit=10,
    tracks_per_playlist=50
)
```

1. Fetches user's liked songs (up to 500)
2. Fetches tracks from user's playlists (configurable)
3. Extracts unique artist IDs
4. Retrieves genre information for all artists
5. Calculates average audio features for all tracks
6. Returns comprehensive taste profile

### Step 2: Recommendation Generation
```python
engine = RecommendationEngine(sp)
recommendations = engine.generate_recommendations(
    analysis=analysis,
    limit=30,
    include_audio_targets=True
)
```

1. Validates available genre seeds with Spotify
2. Selects top 2 artists and top 5 genres as seeds
3. Sets target audio features based on user's averages
4. Calls Spotify's recommendation API
5. Returns list of recommended tracks

### Step 3: Playlist Creation
```python
result = engine.create_recommendation_playlist(
    user_id=user_id,
    recommendations=recommendations,
    playlist_name="My Recommendations",
    public=True
)
```

1. Creates new playlist in user's account
2. Adds tracks in batches (up to 100 per request)
3. Returns playlist ID and Spotify URL

## Spotify API Endpoints Used

| Endpoint | Purpose | Rate Limit |
|----------|---------|------------|
| `/me/tracks` | Get liked songs | 50 per request |
| `/me/playlists` | Get user playlists | 50 per request |
| `/playlists/{id}/tracks` | Get playlist tracks | 100 per request |
| `/artists` | Get artist info & genres | 50 per request |
| `/audio-features` | Get track audio features | 100 per request |
| `/recommendations/available-genre-seeds` | Get valid genres | No pagination |
| `/recommendations` | Get recommendations | 100 per request |
| `/users/{id}/playlists` | Create playlist | N/A |
| `/playlists/{id}/tracks` | Add tracks | 100 per request |

## Configuration Options

### Analysis Parameters
- **include_playlists**: Include user playlists in analysis (default: `true`)
- **playlist_limit**: Max playlists to analyze (default: `10`)
- **tracks_per_playlist**: Max tracks per playlist (default: `50`)

### Recommendation Parameters
- **limit**: Number of recommendations (range: `10-50`, default: `30`)
- **include_audio_targets**: Match audio features (default: `true`)

### Playlist Parameters
- **playlist_name**: Custom name (default: "Recommended Tracks - {date}")
- **playlist_description**: Custom description
- **public**: Playlist visibility (default: `true`)

## Error Handling

The system handles various error scenarios:

1. **No Tracks Found**: Returns error if user has no liked songs or playlists
2. **Invalid Seeds**: Validates genres against Spotify's available seeds
3. **API Errors**: Catches and logs `SpotifyException` errors
4. **Authentication**: Redirects to login if token is invalid
5. **Rate Limiting**: Processes data in batches to respect API limits

## Performance Considerations

- **Batch Processing**: Processes artists and tracks in batches to minimize API calls
- **Deduplication**: Removes duplicate tracks before analysis
- **Caching**: Stores analysis in session to avoid repeated API calls
- **Pagination**: Handles paginated responses for large libraries

## Usage Example

```python
# Initialize with authenticated Spotipy client
sp = spotipy.Spotify(auth=token)

# Analyze taste
analyzer = MusicTasteAnalyzer(sp)
analysis = analyzer.analyze_taste()

# Generate recommendations
engine = RecommendationEngine(sp)
recommendations = engine.generate_recommendations(
    analysis=analysis,
    limit=30
)

# Create playlist
result = engine.create_recommendation_playlist(
    user_id='user_spotify_id',
    recommendations=recommendations,
    playlist_name='Discover Weekly Clone'
)

print(f"Created playlist: {result['playlist_url']}")
```

## Frontend Integration

The dashboard provides:
- **Real-time Analysis**: Shows progress while analyzing
- **Visual Statistics**: Displays genre distribution and audio profile
- **Customization**: Form inputs for playlist preferences
- **Instant Feedback**: Loading states and success/error messages
- **Direct Access**: Link to open created playlist in Spotify

## Future Enhancements

Potential improvements:
1. **Collaborative Filtering**: Compare with similar users
2. **Temporal Analysis**: Track taste evolution over time
3. **Mood-Based**: Filter by mood/activity
4. **Artist Discovery**: Focus on emerging artists
5. **Export Analysis**: Download taste profile as JSON/PDF
6. **Playlist Merging**: Combine multiple playlists intelligently

## Troubleshooting

### Common Issues

**"No recommendations could be generated"**
- User may have very limited music library
- Try disabling audio feature matching
- Check if genres are available in Spotify's seed list

**"Spotify API error: 403"**
- User not registered in app's tester list (development mode)
- Check OAuth scopes include required permissions

**Slow analysis**
- Normal for users with 500+ liked songs
- Consider reducing `playlist_limit` parameter

## Dependencies

- **spotipy** (v2.25.2): Spotify API wrapper
- **Flask** (v3.1.2): Web framework
- **python-dotenv** (v1.2.1): Environment management

## License

Same as main project license.
