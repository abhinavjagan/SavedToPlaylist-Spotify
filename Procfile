web: gunicorn LikedToPlaylist:app --bind 0.0.0.0:$PORT --timeout 120 --graceful-timeout 30 --workers 2 --worker-class sync --max-requests 100 --max-requests-jitter 10 --keep-alive 5
