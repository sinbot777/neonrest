import requests
import logging

API_KEY = "f1d69a02f308c0ef32e37f027316ffc6"

def get_now_playing(username):
    logging.warning(f"Now Playing check for {username}")

    url = "https://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "user.getrecenttracks",
        "user": username,
        "api_key": API_KEY,
        "format": "json",
        "limit": 1
    }

    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        track = data["recenttracks"]["track"][0]

        # Log full track for debugging
        logging.warning(f"Raw track data: {track}")

        # Use safe retrieval
        nowplaying = track.get("@attr", {}).get("nowplaying", "").lower() == "true"
        if nowplaying:
            artist = track["artist"]["#text"]
            title = track["name"]
            return f"{artist} – {title}"
    except Exception as e:
        logging.error(f"Last.fm fetch failed: {e}")

    return None
