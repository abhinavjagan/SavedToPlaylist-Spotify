# SavedToPlaylist-Spotify
Developed a code facilitating seamless conversion of Spotify's liked songs into user-friendly playlists, enhancing the ability to share favorite tunes. The script efficiently compiles and organizes liked tracks, streamlining the process for users to create and exchange personalized music collections.

# Setup
1. Make sure python is already installed on your PC.
2. Go to the Spotify Developers website and sign in to your account.
3. Create a new project in the Developer Dashboard, and copy the generated client ID and client secret. These credentials are essential for authenticating your application with the Spotify API.
4. Inside your newly created project, modify the redirect_uri to "http://127.0.0.1:5000/redirect". This is the URL where Spotify will redirect users after they grant or deny permission for your application to access their data.
5. Clone this repository in your machine and open the folder in IDE of your choice.
6. "pip install spotipy" in the terminal.
7. "pip install flask" in the terminal.
8. Run the Python script. In the textField, provide the necessary configuration details,the client ID, client secret. They can be found in the settings of the project created.
9. In the browser, Log In with your mail ID linked to your Spotify account.
10. Once you run the script, the application will run on "http://127.0.0.1:5000/config" by default.
11. After the program runs successfully, A playlist called "cadence" will be created.

## Deploying to a public host (recommended: Render or Railway)

These steps show a simple way to host the app and point your custom domain to it.

1. Push this repo to GitHub.
2. Create an account on Render (https://render.com) or Railway (https://railway.app) and connect your GitHub repo.
3. Create a new Web Service (Render) / Deploy (Railway). Use the repo and branch you pushed.
	- Build: the platform will run `pip install -r requirements.txt` automatically.
	- Start command: `gunicorn LikedToPlaylist:app --bind 0.0.0.0:$PORT` (we included a `Procfile`).
4. In the service settings, set environment variables:
	- `SPOTIFY_CLIENT_ID` — your app client id
	- `SPOTIFY_CLIENT_SECRET` — your app client secret
	- `SECRET_KEY` — random secret for Flask sessions
	- `FLASK_ENV=production`
5. Deploy. Note the public URL (e.g. `https://your-app.onrender.com`).

### Pointing your domain

1. In Render/Railway, add a Custom Domain (they'll show instructions to verify it).
2. In your DNS provider, create the records the platform asks for:
	- Typically a CNAME pointing `www` to the platform's hostname, or an A record for the root.
	- Example (CNAME): `www.example.com CNAME your-app.onrender.com`.
	- For root domain you may need an A record or ALIAS/ANAME depending on provider.
3. Wait for DNS propagation and enable the custom domain in the Render/Railway dashboard.

### Spotify Redirect URI

1. In the Spotify Developer Dashboard for your app, set the Redirect URI to `https://YOUR_DOMAIN/redirect` (replace with your deployed domain).
2. Save changes in the Spotify app settings.

## Notes & recommendations

- Vercel is not recommended for this app as the playlist creation can be long-running; use Render/Railway/Fly.io which run full processes and support long requests or background workers.
- Store `SPOTIFY_CLIENT_SECRET` and `SECRET_KEY` securely (single place: Render env vars or a secret manager). Do not hardcode in production.
- Consider adding persistent storage for user refresh tokens (SQLite) if you want to avoid re-authorization.

For help wiring up the custom domain or pushing the repo to GitHub I can create a short checklist and the exact commands to run locally.

## GitHub Actions automatic deploy (CI)

This repository includes a GitHub Actions workflow `.github/workflows/ci-deploy.yml` that:

- Installs dependencies and runs a quick smoke-check on push to `main`.
- Optionally triggers a Render deploy via the Render API if you set two repository secrets: `RENDER_API_KEY` and `RENDER_SERVICE_ID`.

Important: Do NOT commit credentials to the repository. Instead set these GitHub Secrets in your repository settings:

- `SPOTIFY_CLIENT_ID` — Spotify app client id
- `SPOTIFY_CLIENT_SECRET` — Spotify app client secret
- `SECRET_KEY` — Flask session secret
- (Optional) `RENDER_API_KEY` — Render API key if you want the workflow to trigger deploys
- (Optional) `RENDER_SERVICE_ID` — Render service id to trigger a deploy

How to add GitHub Secrets:

1. Open your GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret.
2. Add the keys above and their values.

With secrets set, every push to `main` will run CI and trigger a Render deployment (if `RENDER_API_KEY` and `RENDER_SERVICE_ID` are provided).

