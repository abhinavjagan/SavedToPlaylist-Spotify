# 🎵 Quick Start Guide - Music Recommendations

## For End Users

### How to Use the Recommendation System

#### Step 1: Access the Dashboard
1. Visit https://cramzz.space/
2. Click the **"🎯 Get Recommendations"** button
3. Log in with Spotify if prompted

#### Step 2: Generate Your Recommendations
1. Enter a **playlist name** (e.g., "My Weekly Discoveries")
2. Choose **number of tracks** (10-50, recommended: 30)
3. Select preferences:
   - ✅ **Include playlists**: Analyze your playlists too (recommended)
   - ✅ **Match audio characteristics**: Match your energy/mood (recommended)
   - ☐ **Make playlist public**: Share with others (optional)
4. Click **"🎵 Analyze & Generate Playlist"**

#### Step 3: View Your Analysis
After a few seconds, you'll see:
- **📊 Overview**: How many tracks and artists analyzed
- **🎸 Top Genres**: Your most listened-to genres
- **🎛️ Audio Profile**: Your music preferences (energy, danceability, etc.)

#### Step 4: Get Your Playlist
- Wait for the playlist creation (usually 5-10 seconds)
- Click the **"Open in Spotify"** link
- Enjoy your personalized recommendations! 🎉

### What It Does

The system:
1. **Analyzes** your liked songs and playlists
2. **Identifies** your favorite genres and artists
3. **Calculates** your audio preferences (energy, mood, tempo)
4. **Generates** personalized recommendations from Spotify
5. **Creates** a new playlist with these tracks

### Tips for Best Results

✅ **DO:**
- Have at least 50 liked songs for better analysis
- Include playlists for more comprehensive taste profile
- Use "Match audio characteristics" for mood-consistent recommendations
- Try different track limits (20 for focused, 50 for variety)

❌ **DON'T:**
- Expect recommendations if you have very few liked songs
- Worry if it takes 10-15 seconds (analyzing takes time!)
- Create too many playlists at once (Spotify has rate limits)

### Understanding Your Analysis

**Track Count**: Total songs analyzed from your library  
**Unique Artists**: Different artists in your collection  
**Top Genres**: Most common genres (higher number = more tracks)  
**Energy**: How intense/active your music is (0-100%)  
**Danceability**: How suitable for dancing (0-100%)  
**Happiness (Valence)**: How positive/cheerful (0-100%)  

## For Developers

### API Usage

#### Analyze Taste
```bash
curl -X POST https://cramzz.space/api/analyze-taste \
  -H "Content-Type: application/json" \
  -H "Cookie: your-session-cookie" \
  -d '{"include_playlists": true}'
```

**Response:**
```json
{
  "track_count": 450,
  "unique_artists": 120,
  "top_genres": [
    ["indie rock", 45],
    ["electronic", 32]
  ],
  "avg_audio_features": {
    "energy": 0.72,
    "danceability": 0.65
  }
}
```

#### Generate Recommendations
```bash
curl -X POST https://cramzz.space/api/generate-recommendations \
  -H "Content-Type: application/json" \
  -H "Cookie: your-session-cookie" \
  -d '{
    "playlist_name": "AI Recommendations",
    "track_limit": 30,
    "use_audio_features": true,
    "public": false
  }'
```

**Response:**
```json
{
  "success": true,
  "playlist_id": "abc123",
  "playlist_url": "https://open.spotify.com/playlist/abc123",
  "playlist_name": "AI Recommendations",
  "track_count": 30
}
```

### Python Integration

```python
import spotipy
from recommendations import MusicTasteAnalyzer, RecommendationEngine

# Initialize with authenticated client
sp = spotipy.Spotify(auth=access_token)

# Analyze taste
analyzer = MusicTasteAnalyzer(sp)
analysis = analyzer.analyze_taste(
    include_playlists=True,
    playlist_limit=10,
    tracks_per_playlist=50
)

print(f"Analyzed {analysis['track_count']} tracks")
print(f"Top genre: {analysis['top_genres'][0][0]}")

# Generate recommendations
engine = RecommendationEngine(sp)
recommendations = engine.generate_recommendations(
    analysis=analysis,
    limit=30,
    include_audio_targets=True
)

print(f"Got {len(recommendations)} recommendations")

# Create playlist
result = engine.create_recommendation_playlist(
    user_id='your_spotify_user_id',
    recommendations=recommendations,
    playlist_name='Auto-Generated Playlist',
    public=True
)

print(f"Playlist URL: {result['playlist_url']}")
```

### Configuration

**Environment Variables:**
```bash
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SECRET_KEY=your_flask_secret
PUBLIC_URL=https://cramzz.space
```

**Analysis Parameters:**
```python
analyzer.analyze_taste(
    include_playlists=True,    # Analyze playlists too
    playlist_limit=10,         # Max playlists to scan
    tracks_per_playlist=50     # Max tracks per playlist
)
```

**Recommendation Parameters:**
```python
engine.generate_recommendations(
    analysis=analysis_result,
    limit=30,                  # Number of tracks (10-50)
    include_audio_targets=True # Match audio features
)
```

## Troubleshooting

### "No tracks found to analyze"
**Problem**: You don't have any liked songs  
**Solution**: Like some songs in Spotify first, then try again

### "No recommendations could be generated"
**Problem**: Not enough data or invalid seeds  
**Solution**: 
- Ensure you have 20+ liked songs
- Try unchecking "Match audio characteristics"
- Check if you have any playlists

### Analysis takes forever
**Problem**: Large music library (500+ songs)  
**Solution**: This is normal! Analysis can take 15-30 seconds for large libraries

### "Spotify API error: 403"
**Problem**: Not authorized (development mode restriction)  
**Solution**: Contact app owner to be added to tester list

### Playlist created but empty
**Problem**: API error during track addition  
**Solution**: Try again with fewer tracks (e.g., 20 instead of 50)

### Different results each time
**Explanation**: This is expected! Spotify's recommendation algorithm uses randomness to provide variety

## Feature Comparison

| Feature | Save Liked Songs | Get Recommendations |
|---------|------------------|---------------------|
| **Purpose** | Copy liked songs to playlist | Discover new music |
| **Source** | Your liked songs only | Spotify's catalog |
| **Result** | Playlist with your songs | Playlist with new songs |
| **Customization** | Name, privacy | Name, count, privacy, matching |
| **Time** | Fast (~5 sec) | Moderate (~10-15 sec) |
| **Best For** | Organizing | Discovering |

## Advanced Tips

### 1. Niche Genre Discovery
- Uncheck "Include playlists" if you only want recommendations based on liked songs
- This focuses the algorithm on your core taste

### 2. Energy Matching
- Keep "Match audio characteristics" checked for consistent mood
- Uncheck for more variety and exploration

### 3. Regular Updates
- Create weekly recommendations with date in name
- Compare how your taste evolves over time

### 4. Playlist Curation
- Start with 50 tracks
- Remove ones you don't like
- Keep discovering your perfect mix

### 5. Sharing
- Make playlists public to share with friends
- See what recommendations match your taste

## FAQ

**Q: How often can I generate recommendations?**  
A: As often as you want! But note that results will be similar if your library hasn't changed.

**Q: Are the same songs always recommended?**  
A: No, Spotify's algorithm includes randomness for variety.

**Q: Can I customize the genres used?**  
A: Not directly, but the system uses your top genres automatically.

**Q: How accurate are the recommendations?**  
A: Very! They're based on Spotify's algorithm that powers Discover Weekly.

**Q: Can I save my analysis?**  
A: Analysis is stored temporarily in your session. For permanent storage, create the playlist!

**Q: Does this work on mobile?**  
A: Yes! The dashboard is fully responsive.

**Q: How many songs should I have for best results?**  
A: At least 50 liked songs recommended. More is better (up to 500 analyzed).

**Q: Can I delete the playlist later?**  
A: Yes, it's a normal Spotify playlist you can delete anytime.

## Support

For issues or questions:
- 📧 Contact: your-email@example.com
- 📚 Documentation: RECOMMENDATIONS_DOCS.md
- 🐛 Report bugs: GitHub issues
- 💬 Feedback: your-feedback-channel

## Privacy

- ✅ We only read your liked songs and playlists
- ✅ No data is stored permanently
- ✅ Analysis happens in real-time
- ✅ Only you can see your analysis
- ✅ Playlists are created in your account
- ✅ Full control over playlist privacy

Enjoy discovering new music! 🎵✨
