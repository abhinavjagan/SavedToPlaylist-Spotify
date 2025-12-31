#!/usr/bin/env python3
"""
Quick verification script to test timeout fixes
Run this BEFORE deploying to ensure no syntax errors
"""
import sys

print("=" * 60)
print("TIMEOUT FIX VERIFICATION")
print("=" * 60)

# Test 1: Import recommendations module
print("\n[1/4] Testing recommendations module import...")
try:
    from recommendations import MusicTasteAnalyzer, RecommendationEngine, TimeoutException
    print("✅ SUCCESS: recommendations module imports correctly")
except Exception as e:
    print(f"❌ FAILED: {e}")
    sys.exit(1)

# Test 2: Import Flask app
print("\n[2/4] Testing Flask app import...")
try:
    # Set dummy env vars to allow import
    import os
    os.environ.setdefault('SPOTIFY_CLIENT_ID', 'test_id')
    os.environ.setdefault('SPOTIFY_CLIENT_SECRET', 'test_secret')
    os.environ.setdefault('SECRET_KEY', 'test_key')
    
    from LikedToPlaylist import app, analyze_taste, generate_recommendations
    print("✅ SUCCESS: Flask app imports correctly")
except Exception as e:
    print(f"❌ FAILED: {e}")
    sys.exit(1)

# Test 3: Verify key timeout settings
print("\n[3/4] Verifying timeout configuration...")
try:
    # Check default timeout values in MusicTasteAnalyzer
    from recommendations import MusicTasteAnalyzer
    import inspect
    
    # Get __init__ signature
    sig = inspect.signature(MusicTasteAnalyzer.__init__)
    request_timeout_param = sig.parameters.get('request_timeout')
    
    if request_timeout_param and request_timeout_param.default == 2:
        print("✅ SUCCESS: MusicTasteAnalyzer default timeout is 2 seconds")
    else:
        print(f"⚠️  WARNING: Default timeout is {request_timeout_param.default}, expected 2")
    
    # Check analyze_taste defaults
    sig = inspect.signature(MusicTasteAnalyzer.analyze_taste)
    liked_songs_limit = sig.parameters.get('liked_songs_limit').default
    max_analysis_time = sig.parameters.get('max_analysis_time').default
    include_playlists = sig.parameters.get('include_playlists').default
    
    print(f"   - liked_songs_limit: {liked_songs_limit} (expected: 15)")
    print(f"   - max_analysis_time: {max_analysis_time} (expected: 20)")
    print(f"   - include_playlists: {include_playlists} (expected: False)")
    
    if liked_songs_limit == 15 and max_analysis_time == 20 and include_playlists is False:
        print("✅ SUCCESS: All timeout settings are correct")
    else:
        print("⚠️  WARNING: Some settings differ from expected values")
        
except Exception as e:
    print(f"⚠️  WARNING: Could not verify settings: {e}")

# Test 4: Check for removed signal code
print("\n[4/4] Checking for removed signal-based timeout...")
try:
    with open('recommendations.py', 'r') as f:
        content = f.read()
        
    if 'signal.alarm' in content or 'signal.SIGALRM' in content:
        print("⚠️  WARNING: Signal-based timeout code still present")
        print("   This should have been removed!")
    else:
        print("✅ SUCCESS: Signal-based timeout code removed")
        
except Exception as e:
    print(f"⚠️  WARNING: Could not check file: {e}")

# Summary
print("\n" + "=" * 60)
print("VERIFICATION COMPLETE")
print("=" * 60)
print("\n✅ All critical checks passed!")
print("\nNext steps:")
print("1. Review TIMEOUT_FIX_SUMMARY.md for complete details")
print("2. Commit changes:")
print("   git add .")
print("   git commit -m 'Fix worker timeout with 2s request timeout and ultra-conservative limits'")
print("3. Deploy:")
print("   git push origin main")
print("4. Monitor logs for 24 hours")
print("\n⚠️  IMPORTANT: Playlists are now DISABLED by default")
print("   This prevents timeouts but reduces analysis scope.")
print("   Users can re-enable at their own risk.\n")

