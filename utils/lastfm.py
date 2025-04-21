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
        logging.warning(f"Raw track data: {track}")  # DEBUG

        artist = track.get("artist", {}).get("#text", "Unknown Artist")
        title = track.get("name", "Unknown Title")

        image_list = track.get("image", [])
        album_art = next((img["#text"] for img in reversed(image_list) if img.get("#text")), None)

        now_playing = f"{artist} – {title}"

        return {
            "track": now_playing,
            "album_art": album_art
        }

    except Exception as e:
        logging.error(f"Last.fm fetch failed: {e}")
        return {
            "now_playing": None,
            "album_art": None
        }
