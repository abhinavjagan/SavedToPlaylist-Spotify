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
