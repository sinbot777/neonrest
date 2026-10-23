"""Fetch one Last.fm snapshot without blocking profile rendering."""
import logging
import os
import requests

API_KEY = os.environ.get('LASTFM_API_KEY', '')

def get_now_playing(username):
    empty = {'track': None, 'url': None, 'album_art': None, 'is_now_playing': False}
    try:
        response = requests.get('https://ws.audioscrobbler.com/2.0/', params={
            'method': 'user.getrecenttracks', 'user': username,
            'api_key': API_KEY, 'format': 'json', 'limit': 1}, timeout=5)
        response.raise_for_status()
        tracks = response.json().get('recenttracks', {}).get('track', [])
        if not isinstance(tracks, list) or not tracks or not isinstance(tracks[0], dict):
            return empty
        track = tracks[0]
        artist = track.get('artist', {})
        artist = artist.get('#text') if isinstance(artist, dict) else None
        title = track.get('name')
        if not isinstance(title, str) or not title.strip():
            return empty
        artist = artist if isinstance(artist, str) and artist.strip() else 'Unknown Artist'
        images = track.get('image', [])
        art = next((image.get('#text') for image in reversed(images)
            if isinstance(image, dict) and isinstance(image.get('#text'), str) and image['#text']), None) if isinstance(images, list) else None
        attributes = track.get('@attr', {})
        return {'track': f'{artist} – {title}', 'url': track.get('url'),
            'album_art': art, 'is_now_playing': isinstance(attributes, dict) and attributes.get('nowplaying') == 'true'}
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        logging.warning('Last.fm music snapshot unavailable')
        return empty
